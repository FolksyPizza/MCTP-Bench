"""LongBench adapter — long-document QA and reasoning (high context).

Each record is a long context document plus a question; the receiver answers from it. Unlike
the repository suites the source is prose, not code, so there is no code extractor: the document
is the transferable prior context. `transcript` delivers it whole, `summary` condenses it,
`rag` retrieves passages, and `mctp` currently delivers a minimal task packet (a prose-to-graph
extractor is future work, so MCTP's advantage on prose is not yet exercised here — this suite
mainly stresses the long-context transcript baseline and retrieval).

Record fields: `_id`, `task` (subtask type), `input` (question), `context` (the long document),
`answers` (list of acceptable answers). Point at the dataset with `MCTP_LONGBENCH` or
`data/longbench.jsonl`; a bundled sample runs offline. QA-style subsets are scored by any-answer
match; open-ended subsets are left for the judge.
"""
from __future__ import annotations

import json
import os
import re

from .base import Adapter, Task, source_from_repo

_HERE = os.path.dirname(__file__)
_INSTRUCTION = (
    "Answer the question using only the context provided. Be concise and answer directly."
)
# Subtasks with short factual answers we can match; others are judged.
_OBJECTIVE_TASKS = {"narrativeqa", "qasper", "multifieldqa_en", "hotpotqa", "2wikimqa",
                    "musique", "triviaqa", "samsum"}


def _path() -> str:
    env = os.environ.get("MCTP_LONGBENCH")
    if env and os.path.exists(env):
        return env
    full = os.path.join(_HERE, "..", "data", "longbench.jsonl")
    return full if os.path.exists(full) else os.path.join(_HERE, "..", "data",
                                                          "longbench_sample.jsonl")


def _norm_ans(s: str) -> str:
    """Normalize for answer matching: lowercase, drop markdown emphasis and punctuation, collapse
    whitespace. Without this, a correct answer fails on the model's markdown bold, a hyphen, or a
    trailing period (e.g. gold 'Vice Admiral.' vs output '**Vice Admiral**.')."""
    s = (s or "").lower()
    s = re.sub(r"[*`#_]+", " ", s)        # markdown emphasis
    s = re.sub(r"[^a-z0-9 ]", " ", s)     # punctuation
    return re.sub(r"\s+", " ", s).strip()


def _token_f1(pred_toks: list, gold_toks: list) -> float:
    if not pred_toks or not gold_toks:
        return 0.0
    common = sum(min(pred_toks.count(w), gold_toks.count(w)) for w in set(gold_toks))
    if not common:
        return 0.0
    prec, rec = common / len(pred_toks), common / len(gold_toks)
    return 2 * prec * rec / (prec + rec)


def _any_match(answers: list, f1_threshold: float = 0.5):
    """Robust QA scoring: a gold answer passes if its normalized form is contained in the
    normalized output, or if token-F1 against any gold clears `f1_threshold` (covers correct
    answers that are reworded rather than quoted verbatim)."""
    golds = [_norm_ans(a) for a in answers]

    def score(answer: str) -> tuple:
        norm = _norm_ans(answer)
        toks = norm.split()
        contained = any(g and g in norm for g in golds)
        best_f1 = max((_token_f1(toks, g.split()) for g in golds), default=0.0)
        ok = contained or best_f1 >= f1_threshold
        method = "contains" if contained else "f1" if ok else "none"
        return ok, {"answers": answers, "matched": ok, "f1": round(best_f1, 2), "method": method}

    return score


class LongBenchAdapter(Adapter):
    name = "longbench"
    tier = "large"
    default_conditions = ("transcript", "summary", "rag", "mctp")

    def __init__(self, path: str | None = None):
        self.path = path or _path()

    def tasks(self, limit: int | None = None):
        count = 0
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                p = json.loads(line)
                tid = p["_id"]
                answers = p.get("answers", [])
                subtask = p.get("task", "")
                objective = _any_match(answers) if (answers and subtask in _OBJECTIVE_TASKS) \
                    else None
                # Give mctp a graph so its packet references the document (retrievable on demand)
                # rather than an empty packet: the document becomes an artifact node linked to the
                # question. transcript/summary/rag still see the document inline via docs.
                src = source_from_repo(self.name, tid, p["input"],
                                       {"document.txt": p["context"]}, tier=self.tier)
                yield Task(
                    task_id=tid, source=src,
                    receiver_instruction=_INSTRUCTION, objective=objective,
                    gold=answers[0] if answers else "",
                    meta={"subtask": subtask},
                )
                count += 1
                if limit and count >= limit:
                    return
