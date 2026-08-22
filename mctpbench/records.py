"""Run records and the results storage tree.

One `RunRecord` per (suite, task, condition, model, trial). Every run keeps both the raw
capture (verbatim requests, full responses, timestamped output stream) and the parsed fields
(answer, reasoning, native + reference token counts, timing, objective pass) — additively, so
any analysis, scoring, or pricing can be redone from the bare data without re-running a model.

Storage layout (see docs/DATA-MODEL.md):

    results/
      runs/       <suite>/<model>/<condition>.jsonl   parsed run records (small, scannable)
      raw/        <run_id>.jsonl                        verbatim requests + responses + chunks
      outputs/    <run_id>.{prompt,out,think}.txt, <run_id>.timeline.jsonl
      judge/      ensemble judge scores (written by a later pass)
      aggregates/ computed tables (committed)
      configs/    exact batch configs (committed)

`runs/`, `raw/`, and `outputs/` are large and gitignored; they are published as a dataset
release. Only `aggregates/` and `configs/` are committed.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import asdict, dataclass, field

from . import tokenizers

REF_TOKENIZERS = [t for t in tokenizers.available() if t != tokenizers.HEURISTIC] \
    or [tokenizers.HEURISTIC]


@dataclass
class RunRecord:
    run_id: str
    suite: str
    task_id: str
    tier: str
    condition: str                 # transcript | summary | rag | mctp | mctp-learned
    model: str
    model_size_b: float | None
    reasoning: bool
    trial: int
    started_at: str                # iso8601

    # input delivered to the receiver
    context_tokens: int = 0
    packet_node_ids: list = field(default_factory=list)
    prep_tokens: int = 0           # summarizer / embedding cost for this condition

    # MCTP behavior
    retrieved_ids: list = field(default_factory=list)
    retrieved_tokens: int = 0
    codebase_reads: int = 0

    # native token counts (server usage, i.e. the model's own tokenizer)
    prompt_tokens: int = 0
    reasoning_tokens: int = 0
    output_tokens: int = 0
    ref_token_counts: dict = field(default_factory=dict)  # tokenizer -> {prompt,output,reasoning}

    # timing
    ttft_s: float | None = None
    latency_s: float = 0.0

    # objective score (suite scorer, when one exists)
    objective_pass: bool | None = None
    objective_detail: dict = field(default_factory=dict)

    # references to the large text stored under outputs/ and raw/
    prompt_ref: str = ""
    output_ref: str = ""
    reasoning_ref: str = ""
    timeline_ref: str = ""
    raw_ref: str = ""

    # provenance / reproducibility
    runner: str = ""
    endpoint: str = ""
    temperature: float = 0.0
    seed: int | None = None
    max_tokens: int | None = None
    model_digest: str = ""
    harness_commit: str = ""

    def to_json(self) -> dict:
        return asdict(self)


def new_run_id() -> str:
    return uuid.uuid4().hex


def _git_commit(repo_dir: str) -> str:
    try:
        out = subprocess.run(["git", "-C", repo_dir, "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def ref_token_counts(prompt: str, output: str, reasoning: str) -> dict:
    """Reference token counts over each text under the fixed reference tokenizer set, so
    amounts are comparable across models that tokenize differently."""
    counts = {}
    for t in REF_TOKENIZERS:
        try:
            counts[t] = {
                "prompt": tokenizers.count(prompt, t),
                "output": tokenizers.count(output, t),
                "reasoning": tokenizers.count(reasoning, t),
            }
        except Exception:
            continue
    return counts


class ResultStore:
    """Writes the storage tree. `root` is a results/ directory (created if missing)."""

    def __init__(self, root: str, harness_repo: str | None = None):
        self.root = root
        self.harness_commit = _git_commit(harness_repo or os.getcwd())
        for sub in ("runs", "raw", "outputs", "judge", "aggregates", "configs"):
            os.makedirs(os.path.join(root, sub), exist_ok=True)

    def _write_text(self, name: str, text: str) -> str:
        rel = os.path.join("outputs", name)
        with open(os.path.join(self.root, rel), "w") as f:
            f.write(text)
        return rel

    def write_raw(self, run_id: str, result) -> str:
        """Verbatim request(s), full server response chunks, and the timestamped stream."""
        rel = os.path.join("raw", f"{run_id}.jsonl")
        with open(os.path.join(self.root, rel), "w") as f:
            for i, rnd in enumerate(getattr(result, "rounds", []) or []):
                f.write(json.dumps({
                    "round": i,
                    "request": rnd.request,
                    "usage": rnd.usage,
                    "finish_reason": rnd.finish_reason,
                    "t_start": rnd.t_start, "t_end": rnd.t_end, "ttft_s": rnd.ttft_s,
                    "chunks": rnd.chunks,   # every SSE chunk with its wall-clock offset
                }) + "\n")
        return rel

    def write_run(self, record: RunRecord, *, prompt: str, output: str, reasoning: str,
                  timeline: list, raw_result=None) -> RunRecord:
        """Persist one run: raw capture + referenced text + the parsed record."""
        record.harness_commit = record.harness_commit or self.harness_commit
        rid = record.run_id

        record.prompt_ref = self._write_text(f"{rid}.prompt.txt", prompt)
        record.output_ref = self._write_text(f"{rid}.out.txt", output)
        if reasoning:
            record.reasoning_ref = self._write_text(f"{rid}.think.txt", reasoning)
        tl_rel = os.path.join("outputs", f"{rid}.timeline.jsonl")
        with open(os.path.join(self.root, tl_rel), "w") as f:
            for entry in timeline:
                f.write(json.dumps(entry) + "\n")
        record.timeline_ref = tl_rel

        if raw_result is not None and getattr(raw_result, "rounds", None):
            record.raw_ref = self.write_raw(rid, raw_result)

        record.ref_token_counts = ref_token_counts(prompt, output, reasoning)

        shard = os.path.join(self.root, "runs", _safe(record.suite), _safe(record.model))
        os.makedirs(shard, exist_ok=True)
        with open(os.path.join(shard, f"{record.condition}.jsonl"), "a") as f:
            f.write(json.dumps(record.to_json()) + "\n")
        return record

    def write_config(self, name: str, config: dict) -> str:
        rel = os.path.join("configs", name)
        with open(os.path.join(self.root, rel), "w") as f:
            json.dump(config, f, indent=2, sort_keys=True)
        return rel


def _safe(name: str) -> str:
    """Filesystem-safe path segment (model ids contain '/', ':')."""
    return "".join(c if c.isalnum() or c in "-_.=" else "_" for c in name)
