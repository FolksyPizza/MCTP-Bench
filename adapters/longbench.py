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


def _any_match(answers: list):
    golds = [re.sub(r"\s+", " ", a.strip().lower()) for a in answers]

    def score(answer: str) -> tuple:
        a = re.sub(r"\s+", " ", (answer or "").strip().lower())
        ok = any(g and g in a for g in golds)
        return ok, {"answers": answers, "matched": ok}

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
