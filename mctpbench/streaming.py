"""Streaming model runner — captures raw output and second-by-second timing.

`StreamingRunner` runs a real model over an OpenAI-compatible /v1/chat/completions endpoint
with `stream=true`, so every generated chunk is timestamped as it arrives. Unlike the
non-streaming `OpenAICompatRunner`, it returns the full raw capture the data model requires:
the exact request payload(s), every streamed chunk with its wall-clock offset, the server's
`usage` block (native token counts), and the assembled answer / reasoning text.

It handles retrieve-on-demand the same way as the non-streaming runner: if the model ends a
reply with `RETRIEVE <id> ...`, the requested artifacts are appended and it is asked again;
each round is captured separately.

Stdlib only (urllib + time), so the package stays dependency-free.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field

from .runner import DEFAULT_QUESTION, OpenAICompatRunner, RunResult, _parse_retrieve

_answer_text = OpenAICompatRunner._answer_text


@dataclass
class Round:
    """One request/response exchange (initial answer, then one per retrieve round)."""
    request: dict                       # exact payload sent to the server
    chunks: list = field(default_factory=list)  # [{"t": offset_s, "raw": <sse-json>}]
    content: str = ""                   # assembled answer text (delta.content)
    reasoning: str = ""                 # assembled chain-of-thought (delta.reasoning*)
    usage: dict | None = None           # server-reported token usage, if any
    finish_reason: str | None = None
    ttft_s: float | None = None         # time to first content/reasoning token
    t_start: float = 0.0                # offset from run start when the request was sent
    t_end: float = 0.0                  # offset when the response completed


@dataclass
class StreamResult(RunResult):
    """A RunResult enriched with everything captured during streaming."""
    rounds: list = field(default_factory=list)   # list[Round]
    reasoning: str = ""
    prompt_text: str = ""                          # the receiver's full user prompt (round 1)
    started_at: float = 0.0                        # wall-clock epoch seconds at run start

    def timeline(self) -> list:
        """Flat [offset_seconds, text_delta] stream across all rounds, in arrival order.

        Offsets are measured from the start of the run, so the exact text produced at any
        second is reconstructable (retrieve rounds continue on the same clock)."""
        out = []
        for rnd in self.rounds:
            for ch in rnd.chunks:
                delta = _chunk_text(ch["raw"])
                if delta:
                    out.append([round(ch["t"], 4), delta])
        return out

    def native_tokens(self) -> dict:
        """Sum the server-reported usage across rounds into prompt/reasoning/output counts."""
        prompt = output = reasoning = 0
        have = False
        for rnd in self.rounds:
            u = rnd.usage or {}
            if u:
                have = True
            prompt += int(u.get("prompt_tokens", 0) or 0)
            output += int(u.get("completion_tokens", 0) or 0)
            details = u.get("completion_tokens_details") or {}
            reasoning += int(details.get("reasoning_tokens", 0) or 0)
        if not have:
            return {}
        # Some servers fold reasoning into completion_tokens; expose both, do not double count.
        return {"prompt_tokens": prompt, "output_tokens": output,
                "reasoning_tokens": reasoning}


def _chunk_text(raw: dict) -> str:
    """Content delta from a streamed chunk (answer only, not reasoning)."""
    try:
        return raw["choices"][0]["delta"].get("content") or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _chunk_reasoning(raw: dict) -> str:
    try:
        delta = raw["choices"][0]["delta"]
    except (KeyError, IndexError, TypeError):
        return ""
    for key in ("reasoning", "reasoning_content", "thinking"):
        if delta.get(key):
            return str(delta[key])
    return ""


class StreamingRunner:
    """Streaming counterpart to OpenAICompatRunner.

    Configure via constructor or environment: MCTP_MODEL_URL (default http://localhost:8000/v1),
    MCTP_MODEL, MCTP_API_KEY (default "EMPTY"; vLLM/Ollama ignore it). `seed` is forwarded when
    the server supports it, for reproducibility."""

    def __init__(self, base_url="http://localhost:8000/v1", model="", api_key="EMPTY",
                 question=None, temperature=0.0, max_tokens=2048, seed=1,
                 max_retrieve_rounds=1, timeout=600):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.question = question or DEFAULT_QUESTION
        self.temperature = temperature
        self.max_tokens = int(max_tokens)
        self.seed = seed
        self.max_retrieve_rounds = max_retrieve_rounds
        self.timeout = timeout
        self.name = f"model:{self.model}" if self.model else "model"

    def _payload(self, messages: list) -> dict:
        return {
            "model": self.model, "messages": messages,
            "temperature": self.temperature, "max_tokens": self.max_tokens,
            "seed": self.seed, "stream": True,
            "stream_options": {"include_usage": True},
        }

    def _stream(self, messages: list, run_start: float) -> Round:
        payload = self._payload(messages)
        rnd = Round(request=payload, t_start=time.monotonic() - run_start)
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            for line in resp:
                line = line.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    raw = json.loads(data)
                except json.JSONDecodeError:
                    continue
                offset = time.monotonic() - run_start
                rnd.chunks.append({"t": offset, "raw": raw})
                if raw.get("usage"):
                    rnd.usage = raw["usage"]
                c, r = _chunk_text(raw), _chunk_reasoning(raw)
                if (c or r) and rnd.ttft_s is None:
                    rnd.ttft_s = offset
                rnd.content += c
                rnd.reasoning += r
                try:
                    fr = raw["choices"][0].get("finish_reason")
                    if fr:
                        rnd.finish_reason = fr
                except (KeyError, IndexError, TypeError):
                    pass
        rnd.t_end = time.monotonic() - run_start
        return rnd

    def summarize(self, text: str) -> tuple:
        """Same-model summary condition: condense prior context into a handoff. Returns
        (summary_text, prep_tokens) where prep_tokens is the summarizer's native input+output
        usage (the inference the `summary` condition must pay for)."""
        instruction = (
            "Condense the following into a concise handoff for another agent continuing this "
            "work. Preserve the current approach, decisions, constraints, and any rejected "
            "alternative and the reason it was rejected. Omit incidental chatter."
        )
        messages = [{"role": "user", "content": f"{instruction}\n\n---\n{text}"}]
        rnd = self._stream(messages, time.monotonic())
        summary = _round_answer(rnd)
        u = rnd.usage or {}
        prep = int(u.get("prompt_tokens", 0) or 0) + int(u.get("completion_tokens", 0) or 0)
        return summary, prep

    def run(self, task: str, context: str, retrievable: dict, question=None) -> StreamResult:
        system = ("You continue another agent's work. Use only the provided context; do not "
                  "invent files or facts.")
        user = f"{question or self.question}\n\nTASK: {task}\n\n--- CONTEXT ---\n{context}"
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]

        run_start = time.monotonic()
        started_at = time.time()
        rounds = [self._stream(messages, run_start)]
        answer = _round_answer(rounds[-1])

        retrieved: list = []
        for _ in range(self.max_retrieve_rounds):
            ids = [i for i in _parse_retrieve(answer)
                   if i in retrievable and i not in retrieved]
            if not ids:
                break
            retrieved += ids
            blob = "\n\n".join(f"[RETRIEVED {i}]\n{retrievable[i]}" for i in ids)
            messages += [
                {"role": "assistant", "content": answer},
                {"role": "user", "content": f"{blob}\n\nNow give your final numbered answer."},
            ]
            rounds.append(self._stream(messages, run_start))
            answer = _round_answer(rounds[-1])

        return StreamResult(
            answer=answer, retrieved_ids=retrieved, codebase_reads=0,
            rounds=rounds, reasoning=rounds[-1].reasoning, prompt_text=user,
            started_at=started_at,
        )


def _round_answer(rnd: Round) -> str:
    """Final answer for a round, applying the same reasoning-model handling as the
    non-streaming runner (strip <think>, fall back to reasoning if content is empty)."""
    return _answer_text({"content": rnd.content, "reasoning": rnd.reasoning})
