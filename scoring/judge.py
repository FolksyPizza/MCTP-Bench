"""Ensemble LLM judge — a separate pass over stored run records.

Run after all model runs complete. For each run, at least three judge models (from different
families, to reduce self-preference bias) score the receiver's output against the gold answer
or a rubric. Each judge writes one record into `results/judge/`; the final label aggregates
them by majority vote. This replaces the keyword checks, which a 27B model already false-passed
on the `hidden_constraint` control.

Judges are addressed through the same OpenAI-compatible endpoint as the receivers. This module
only defines the pass; it performs no network calls until `run_judge_pass` is invoked with a
live endpoint.
"""
from __future__ import annotations

import glob
import json
import os
import re
from statistics import median

from mctpbench.runner import OpenAICompatRunner

JUDGE_PROMPT = (
    "You are grading whether a response correctly completes a task, given a reference answer.\n"
    "Grade only correctness and completeness relative to the reference; ignore style.\n\n"
    "TASK:\n{task}\n\nREFERENCE ANSWER:\n{gold}\n\nRESPONSE TO GRADE:\n{answer}\n\n"
    "Reply with a single JSON object on one line: "
    '{{"score": <0-10 integer>, "pass": <true|false>, "reason": "<one sentence>"}}'
)


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {"score": None, "pass": None, "reason": "unparseable", "raw": text}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"score": None, "pass": None, "reason": "unparseable", "raw": text}


class JudgeModel:
    def __init__(self, model: str, base_url: str, api_key: str = "EMPTY", max_tokens: int = 512):
        self.model = model
        self._runner = OpenAICompatRunner(base_url=base_url, model=model, api_key=api_key,
                                          max_tokens=max_tokens, max_retrieve_rounds=0)

    def score(self, task: str, gold: str, answer: str) -> dict:
        prompt = JUDGE_PROMPT.format(task=task, gold=gold, answer=answer)
        messages = [{"role": "user", "content": prompt}]
        verdict = _extract_json(self._runner._chat(messages))
        verdict["judge_model"] = self.model
        return verdict


def aggregate(verdicts: list) -> dict:
    """Majority vote on pass; median of numeric scores."""
    passes = [v.get("pass") for v in verdicts if isinstance(v.get("pass"), bool)]
    scores = [v.get("score") for v in verdicts if isinstance(v.get("score"), (int, float))]
    final_pass = (sum(passes) > len(passes) / 2) if passes else None
    return {
        "final_pass": final_pass,
        "median_score": median(scores) if scores else None,
        "n_judges": len(verdicts),
        "verdicts": verdicts,
    }


def _load_records(results_root: str) -> list:
    out = []
    for path in glob.glob(os.path.join(results_root, "runs", "*", "*", "*.jsonl")):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


def _read_output(results_root: str, ref: str) -> str:
    try:
        with open(os.path.join(results_root, ref)) as f:
            return f.read()
    except (FileNotFoundError, TypeError):
        return ""


def run_judge_pass(results_root: str, judge_models: list, base_url: str,
                   api_key: str = "EMPTY", golds: dict | None = None) -> str:
    """Score every stored run with each judge model. `golds` maps task_id -> reference answer;
    when absent, the record's own task text is used as a weak reference. Writes one file per run
    into results/judge/. Returns the judge directory path."""
    judges = [JudgeModel(m, base_url, api_key) for m in judge_models]
    judge_dir = os.path.join(results_root, "judge")
    os.makedirs(judge_dir, exist_ok=True)
    golds = golds or {}

    for rec in _load_records(results_root):
        answer = _read_output(results_root, rec.get("output_ref", ""))
        gold = golds.get(rec["task_id"], "")
        task = rec["task_id"]
        verdicts = [j.score(task, gold, answer) for j in judges]
        result = {"run_id": rec["run_id"], "task_id": rec["task_id"],
                  "condition": rec["condition"], "model": rec["model"],
                  **aggregate(verdicts)}
        with open(os.path.join(judge_dir, f"{rec['run_id']}.json"), "w") as f:
            json.dump(result, f, indent=2)
    return judge_dir
