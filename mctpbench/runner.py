"""Agent runners — the seam where an "Agent B" produces an answer from a context.

`AgentRunner.run(task, context, retrievable)` returns a RunResult. `retrievable` maps
artifact-id -> full source for retrieve-on-demand.

- `MockRunner` is deterministic and model-free: it validates the harness but is not an efficacy
  measurement.
- `OpenAICompatRunner` runs a real model over an OpenAI-compatible /v1/chat/completions endpoint
  (vLLM, Ollama, or any compatible server). It handles one or more rounds of retrieve-on-demand:
  if the model ends a reply with `RETRIEVE <id> ...`, the requested artifacts are appended and it
  is asked again. Stdlib only (urllib), so the package stays dependency-free.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field


@dataclass
class RunResult:
    answer: str
    retrieved_ids: list = field(default_factory=list)
    codebase_reads: int = 0


class MockRunner:
    """Deterministic, scenario-agnostic plumbing stand-in. It "reads" the delivered context
    (echoing it as the answer) and models retrieve-on-demand: if the packet gives artifact
    references but no inlined source, it pulls the primary code artifact before answering.

    NOTE: its correctness score is trivial (it echoes the context) and is NOT an efficacy claim;
    it validates token accounting, retrieve mechanics, and episode logging. Real correctness
    comes from a model runner."""

    name = "mock"

    def run(self, task: str, context: str, retrievable: dict, question=None) -> RunResult:
        retrieved = []
        only_references = "RETRIEVE " in context and "class " not in context
        if only_references and retrievable:
            aid = max(retrievable, key=lambda k: len(retrievable[k]))
            retrieved.append(aid)
            context += f"\n\n[RETRIEVED {aid}]\n{retrievable[aid]}"
        return RunResult(answer=context, retrieved_ids=retrieved)


DEFAULT_QUESTION = (
    "You are Agent B, continuing work handed off by a previous agent. Using ONLY the context "
    "below, answer concisely in this numbered format:\n"
    "1. The recommended approach or fix.\n"
    "2. Where it goes and the key detail (function/symbol, ordering, or constraint).\n"
    "3. Any alternative that was considered and rejected, and why (or 'none mentioned').\n"
    "4. Anything still missing that you would need to implement confidently.\n"
    "If the ARTIFACTS section lists a file as a reference and you genuinely need its full source, "
    "end your reply with a single line: RETRIEVE <id> [<id> ...]."
)


def _parse_retrieve(text: str) -> list:
    """Return the ids named on a trailing `RETRIEVE ...` line (filtered against the packet later)."""
    m = re.search(r"(?im)^\s*RETRIEVE\s+(.+)$", text or "")
    if not m:
        return []
    return re.findall(r"[A-Za-z0-9_\-]+", m.group(1))


class OpenAICompatRunner:
    """Run a real model via an OpenAI-compatible chat endpoint.

    Configure via constructor or environment: ASTP_MODEL_URL (default http://localhost:8000/v1),
    ASTP_MODEL, ASTP_API_KEY (default "EMPTY"; vLLM/Ollama ignore it)."""

    def __init__(self, base_url=None, model=None, api_key=None, question=None,
                 temperature=0.0, max_tokens=None, max_retrieve_rounds=1, timeout=300):
        self.base_url = (base_url or os.environ.get("ASTP_MODEL_URL",
                                                    "http://localhost:8000/v1")).rstrip("/")
        self.model = model or os.environ.get("ASTP_MODEL", "")
        self.api_key = api_key or os.environ.get("ASTP_API_KEY", "EMPTY")
        self.question = question or DEFAULT_QUESTION
        self.temperature = temperature
        # Reasoning models spend most of the budget on hidden thinking before the answer; if the
        # cap is hit mid-thought the final answer is never produced. Non-reasoning models stop
        # early regardless, so a generous default is safe. Raise it (flag or ASTP_MAX_TOKENS) for
        # heavy reasoners (e.g. 4096+).
        self.max_tokens = int(max_tokens or os.environ.get("ASTP_MAX_TOKENS", 2048))
        self.max_retrieve_rounds = max_retrieve_rounds
        self.timeout = timeout
        self.name = f"model:{self.model}" if self.model else "model"

    def _chat(self, messages: list) -> str:
        body = json.dumps({
            "model": self.model, "messages": messages,
            "temperature": self.temperature, "max_tokens": self.max_tokens,
        }).encode()
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        return self._answer_text(data["choices"][0]["message"])

    @staticmethod
    def _answer_text(msg: dict) -> str:
        """Extract the final answer, handling reasoning models: strip any <think>...</think>
        block from content, and fall back to a separate reasoning field if content is empty
        (some servers, e.g. Ollama for qwen3, put chain-of-thought in `reasoning`)."""
        content = re.sub(r"(?is)<think>.*?</think>", "", msg.get("content") or "").strip()
        if content:
            return content
        for key in ("reasoning", "reasoning_content", "thinking"):
            if msg.get(key):
                return str(msg[key]).strip()
        return ""

    def run(self, task: str, context: str, retrievable: dict, question=None) -> RunResult:
        system = ("You continue another agent's work. Use only the provided context; do not "
                  "invent files or facts.")
        user = f"{question or self.question}\n\nTASK: {task}\n\n--- CONTEXT ---\n{context}"
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        answer = self._chat(messages)

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
            answer = self._chat(messages)
        return RunResult(answer=answer, retrieved_ids=retrieved)
