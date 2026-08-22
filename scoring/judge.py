"""Ensemble cross-review judging — a separate pass over stored run records.

Scoring is deferred: all receiver runs are recorded first (raw + parsed), then this pass scores
them without re-running any receiver. The pass has three stages, and stores every judge
input/output so the scoring itself is auditable and re-aggregatable:

1. Independent scoring. Each of several judge models (mixed families, to reduce self-preference
   bias) scores each output `samples_per_judge` times at nonzero temperature. Two samples per
   model expose a judge's own instability.
2. Cross-review. Each judge is shown the other judges' assessments and asked to critique them
   and give a final judgment. This surfaces disagreement and lets a judge correct an outlier.
3. Aggregation. The final label is the majority vote over the post-review pass/fail and the
   median of the post-review scores; inter-judge disagreement and the round-1→round-2 shift are
   recorded alongside.

Judges are addressed through the same OpenAI-compatible endpoint as the receivers. Nothing is
sent until `run_judge_pass` is called with a live endpoint.
"""
from __future__ import annotations

import glob
import json
import os
import re
from statistics import median, pstdev

from mctpbench.runner import OpenAICompatRunner

SCORE_PROMPT = (
    "You are grading whether a response correctly completes a task, given a reference answer.\n"
    "Grade only correctness and completeness relative to the reference; ignore style.\n\n"
    "TASK:\n{task}\n\nREFERENCE ANSWER:\n{gold}\n\nRESPONSE TO GRADE:\n{answer}\n\n"
    "Reply with a single JSON object on one line: "
    '{{"score": <0-10 integer>, "pass": <true|false>, "reason": "<one sentence>"}}'
)

REVIEW_PROMPT = (
    "You are one of several independent graders of the same response. Below are the task, the "
    "reference answer, the response, and the other graders' assessments. Critique the other "
    "assessments: note any grader that is too lenient or too harsh, or any factual error in "
    "their reasoning. Then give your own final judgment.\n\n"
    "TASK:\n{task}\n\nREFERENCE ANSWER:\n{gold}\n\nRESPONSE GRADED:\n{answer}\n\n"
    "OTHER GRADERS' ASSESSMENTS:\n{others}\n\n"
    "Reply with a single JSON object on one line: "
    '{{"final_score": <0-10 integer>, "final_pass": <true|false>, '
    '"critique": "<one or two sentences>"}}'
)


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {"_unparseable": True, "raw": text}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"_unparseable": True, "raw": text}


class JudgeModel:
    def __init__(self, model: str, base_url: str, api_key: str = "EMPTY",
                 temperature: float = 0.3, max_tokens: int = 512):
        self.model = model
        self._runner = OpenAICompatRunner(base_url=base_url, model=model, api_key=api_key,
                                          temperature=temperature, max_tokens=max_tokens,
                                          max_retrieve_rounds=0)

    def _ask(self, prompt: str) -> tuple:
        raw = self._runner._chat([{"role": "user", "content": prompt}])
        return _extract_json(raw), raw

    def score(self, task: str, gold: str, answer: str) -> tuple:
        return self._ask(SCORE_PROMPT.format(task=task, gold=gold, answer=answer))

    def review(self, task: str, gold: str, answer: str, others: str) -> tuple:
        return self._ask(REVIEW_PROMPT.format(task=task, gold=gold, answer=answer, others=others))


def _num(v):
    return v if isinstance(v, (int, float)) else None


def aggregate(round1: list, round2: list) -> dict:
    """round1: per-sample score verdicts. round2: per-judge post-review verdicts."""
    r1_scores = [_num(v.get("score")) for v in round1 if _num(v.get("score")) is not None]
    r2_scores = [_num(v.get("final_score")) for v in round2
                 if _num(v.get("final_score")) is not None]
    r2_pass = [v.get("final_pass") for v in round2 if isinstance(v.get("final_pass"), bool)]
    final_pass = (sum(r2_pass) > len(r2_pass) / 2) if r2_pass else None
    return {
        "final_pass": final_pass,
        "final_score": median(r2_scores) if r2_scores else None,
        "n_judges": len(round2),
        "judge_disagreement": round(pstdev(r2_scores), 3) if len(r2_scores) > 1 else 0.0,
        "sample_instability": round(pstdev(r1_scores), 3) if len(r1_scores) > 1 else 0.0,
        "score_shift_after_review": (
            round((median(r2_scores) - median(r1_scores)), 3)
            if r1_scores and r2_scores else None),
    }


def _others_blurb(per_judge: dict, exclude: str) -> str:
    lines = []
    for jm, v in per_judge.items():
        if jm == exclude:
            continue
        lines.append(f"- {jm}: score={v.get('score')} pass={v.get('pass')} "
                     f"reason={v.get('reason')!r}")
    return "\n".join(lines) or "(no other assessments)"


def judge_one(judges: list, task: str, gold: str, answer: str, samples_per_judge: int) -> dict:
    """Run the three stages for one output. Returns a full record including raw judge I/O."""
    round1, per_judge_mean = [], {}
    for j in judges:
        samples = []
        for s in range(samples_per_judge):
            verdict, raw = j.score(task, gold, answer)
            entry = {"judge_model": j.model, "sample": s, "raw": raw, **verdict}
            round1.append(entry)
            samples.append(verdict)
        # A judge's round-1 summary for its peers = its first parseable sample.
        summary = next((v for v in samples if not v.get("_unparseable")), samples[0])
        per_judge_mean[j.model] = summary

    round2 = []
    for j in judges:
        others = _others_blurb(per_judge_mean, exclude=j.model)
        verdict, raw = j.review(task, gold, answer, others)
        round2.append({"judge_model": j.model, "raw": raw, **verdict})

    return {"round1": round1, "round2": round2, **aggregate(round1, round2)}


def _load_records(results_root: str) -> list:
    out = []
    for path in glob.glob(os.path.join(results_root, "runs", "*", "*", "*.jsonl")):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


def _read(results_root: str, ref: str) -> str:
    try:
        with open(os.path.join(results_root, ref)) as f:
            return f.read()
    except (FileNotFoundError, TypeError):
        return ""


def run_judge_pass(results_root: str, judge_models: list, base_url: str, api_key: str = "EMPTY",
                   golds: dict | None = None, samples_per_judge: int = 2,
                   temperature: float = 0.3, only_conditions=None) -> str:
    """Score every stored run with the cross-review ensemble. `golds` maps task_id -> reference
    answer. Writes one file per run into results/judge/ with all judge I/O. Returns that dir."""
    judges = [JudgeModel(m, base_url, api_key, temperature=temperature) for m in judge_models]
    judge_dir = os.path.join(results_root, "judge")
    os.makedirs(judge_dir, exist_ok=True)
    golds = golds or {}

    for rec in _load_records(results_root):
        if only_conditions and rec["condition"] not in only_conditions:
            continue
        answer = _read(results_root, rec.get("output_ref", ""))
        gold = golds.get(rec["task_id"], rec.get("task_id", ""))
        result = judge_one(judges, rec["task_id"], gold, answer, samples_per_judge)
        out = {"run_id": rec["run_id"], "task_id": rec["task_id"],
               "condition": rec["condition"], "model": rec["model"], "trial": rec.get("trial"),
               "judge_models": judge_models, "samples_per_judge": samples_per_judge,
               **result}
        with open(os.path.join(judge_dir, f"{rec['run_id']}.json"), "w") as f:
            json.dump(out, f, indent=2)
    return judge_dir
