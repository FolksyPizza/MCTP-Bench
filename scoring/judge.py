"""Ensemble cross-review judging — a separate pass over stored run records.

Scoring is deferred: all receiver runs are recorded first (raw + parsed), then this pass scores
them without re-running any receiver. The pass has three stages, and stores every judge
input/output so the scoring itself is auditable and re-aggregatable:

1. Independent scoring (the PRIMARY label). Each of several judge models (mixed families, to
   reduce self-preference bias) scores each output `samples_per_judge` times at nonzero
   temperature. Each judge is reduced to one verdict (median score, majority pass); the panel
   aggregates those by majority/median. This is the reported metric — a panel of mixed-family
   judges — and it is validated against a human-labeled sample. Two samples per judge expose the
   judge's own instability.
2. Cross-review (a SECONDARY signal). Each judge is then shown the other judges' assessments and
   asked to critique them and give a final judgment. This is reported as an ablation — how often
   peer critique flips the panel and how far scores shift — not as the ground truth, because
   showing peers' verdicts introduces anchoring. It can be disabled (`cross_review=False`).
3. Aggregation. The panel label and its disagreement/instability are primary; the post-review
   label, whether it flips the panel, and the score shift are recorded alongside as secondary.

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

    def score(self, task: str, gold: str, answer: str, native_note: str = "") -> tuple:
        prompt = SCORE_PROMPT.format(task=task, gold=gold, answer=answer)
        if native_note:
            prompt += f"\n\n{native_note}"
        return self._ask(prompt)

    def review(self, task: str, gold: str, answer: str, others: str) -> tuple:
        return self._ask(REVIEW_PROMPT.format(task=task, gold=gold, answer=answer, others=others))


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _majority(bools: list):
    bools = [b for b in bools if isinstance(b, bool)]
    return (sum(bools) > len(bools) / 2) if bools else None


def aggregate_panel(per_judge: dict) -> dict:
    """PRIMARY label: the independent panel. Each judge is reduced to one verdict (median of
    its samples for the score, majority for pass); the panel aggregates those. This is the
    reported metric — a panel of mixed-family judges, majority/median — with cross-review kept
    separate below so peer anchoring does not enter the headline number."""
    judge_scores, judge_passes, within = [], [], []
    for v in per_judge.values():
        if v["scores"]:
            judge_scores.append(median(v["scores"]))
            within.append(pstdev(v["scores"]) if len(v["scores"]) > 1 else 0.0)
        jp = _majority(v["passes"])
        if jp is not None:
            judge_passes.append(jp)
    return {
        "final_pass": _majority(judge_passes),                 # PRIMARY
        "final_score": median(judge_scores) if judge_scores else None,
        "n_judges": len(per_judge),
        "judge_disagreement": round(pstdev(judge_scores), 3) if len(judge_scores) > 1 else 0.0,
        "sample_instability": round(sum(within) / len(within), 3) if within else 0.0,
    }


def aggregate_review(round2: list, panel: dict) -> dict:
    """SECONDARY signal: post cross-review. Reported as an ablation, not the ground truth."""
    scores = [_num(v.get("final_score")) for v in round2
              if _num(v.get("final_score")) is not None]
    passes = [v.get("final_pass") for v in round2 if isinstance(v.get("final_pass"), bool)]
    review_score = median(scores) if scores else None
    shift = (round(review_score - panel["final_score"], 3)
             if review_score is not None and panel.get("final_score") is not None else None)
    return {
        "review_pass": _majority(passes),
        "review_score": review_score,
        "review_flips_panel": (panel.get("final_pass") is not None
                               and _majority(passes) is not None
                               and _majority(passes) != panel["final_pass"]),
        "score_shift_after_review": shift,
    }


def _others_blurb(per_judge: dict, exclude: str) -> str:
    lines = []
    for jm, v in per_judge.items():
        if jm == exclude:
            continue
        s = v["summary"]
        lines.append(f"- {jm}: score={s.get('score')} pass={s.get('pass')} "
                     f"reason={s.get('reason')!r}")
    return "\n".join(lines) or "(no other assessments)"


def judge_one(judges: list, task: str, gold: str, answer: str, samples_per_judge: int,
              cross_review: bool = True, native_note: str = "") -> dict:
    """Score one output. Returns a full record including raw judge I/O. The primary label is
    the independent panel; cross-review (if enabled) is a separate, secondary layer. `native_note`
    (e.g. a SWE-bench test-harness verdict) is shown to each judge as context when present."""
    round1, per_judge = [], {}
    for j in judges:
        scores, passes, first = [], [], None
        for s in range(samples_per_judge):
            verdict, raw = j.score(task, gold, answer, native_note=native_note)
            round1.append({"judge_model": j.model, "sample": s, "raw": raw, **verdict})
            if _num(verdict.get("score")) is not None:
                scores.append(verdict["score"])
            if isinstance(verdict.get("pass"), bool):
                passes.append(verdict["pass"])
            if first is None and not verdict.get("_unparseable"):
                first = verdict
        per_judge[j.model] = {"scores": scores, "passes": passes, "summary": first or {}}

    result = {"round1": round1, **aggregate_panel(per_judge)}

    if cross_review:
        round2 = []
        for j in judges:
            others = _others_blurb(per_judge, exclude=j.model)
            verdict, raw = j.review(task, gold, answer, others)
            round2.append({"judge_model": j.model, "raw": raw, **verdict})
        result["round2"] = round2
        result.update(aggregate_review(round2, result))
    return result


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
                   temperature: float = 0.3, cross_review: bool = True,
                   only_conditions=None) -> str:
    """Score every stored run. The primary label is the independent panel; `cross_review` adds
    the secondary peer-critique layer. `golds` maps task_id -> reference answer. Writes one file
    per run into results/judge/ with all judge I/O. Returns that dir."""
    judges = [JudgeModel(m, base_url, api_key, temperature=temperature) for m in judge_models]
    judge_dir = os.path.join(results_root, "judge")
    os.makedirs(judge_dir, exist_ok=True)
    golds = golds or {}

    # SWE-bench native test verdicts (when the native pass has run) are shown to the judges.
    try:
        from scoring.swebench_native import native_results
        native = native_results(results_root)
    except Exception:
        native = {}

    for rec in _load_records(results_root):
        if only_conditions and rec["condition"] not in only_conditions:
            continue
        answer = _read(results_root, rec.get("output_ref", ""))
        gold = golds.get(rec["task_id"], rec.get("task_id", ""))
        note = ""
        nat = native.get(rec["run_id"])
        if nat is not None:
            note = ("For reference, an automated test harness reports this response's patch "
                    f"{'RESOLVED' if nat['native_pass'] else 'did NOT resolve'} the issue.")
        result = judge_one(judges, rec["task_id"], gold, answer, samples_per_judge,
                           cross_review=cross_review, native_note=note)
        out = {"run_id": rec["run_id"], "task_id": rec["task_id"],
               "condition": rec["condition"], "model": rec["model"], "trial": rec.get("trial"),
               "judge_models": judge_models, "samples_per_judge": samples_per_judge,
               **result}
        with open(os.path.join(judge_dir, f"{rec['run_id']}.json"), "w") as f:
            json.dump(out, f, indent=2)
    return judge_dir
