"""Multi-file adapter — medium-context reasoning and bug-fix tasks across a few files.

Each task is a small project snapshot (a handful of files, ~1–2k tokens) plus a question or a
bug to fix whose answer depends on more than one file. The extractor turns the snapshot into
ASTP state so all four conditions are meaningful. This is the medium-context tier between the
stateless low-context suites and the large-repository suites.

Record fields: `task_id`, `files` (path -> content), `task`, and one of `gold_line` (a corrected
line, scored by line match) or `gold` (a phrase, scored by substring match); tasks with neither
are left for the judge. Point at the dataset with `ASTP_MULTIFILE` or `data/multifile.jsonl`; a
bundled sample runs offline.
"""
from __future__ import annotations

import json
import os
import sys

from .base import Adapter, Task, source_from_repo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scoring.objective import exact_match, line_match  # noqa: E402

_HERE = os.path.dirname(__file__)
_INSTRUCTION = (
    "Answer the question about the project below using the provided context. If a code fix is "
    "asked for, give the corrected line inside a ```python code block; otherwise answer concisely."
)


def _path() -> str:
    env = os.environ.get("ASTP_MULTIFILE")
    if env and os.path.exists(env):
        return env
    full = os.path.join(_HERE, "..", "data", "multifile.jsonl")
    return full if os.path.exists(full) else os.path.join(_HERE, "..", "data",
                                                          "multifile_sample.jsonl")


class MultiFileAdapter(Adapter):
    name = "multifile"
    tier = "medium"
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
                tid = p["task_id"]
                if p.get("gold_line"):
                    objective, gold = line_match(p["gold_line"]), p["gold_line"]
                elif p.get("gold"):
                    objective, gold = exact_match(p["gold"]), p["gold"]
                else:
                    objective, gold = None, ""
                src = source_from_repo(self.name, tid, p["task"], p["files"], tier=self.tier)
                yield Task(task_id=tid, source=src, receiver_instruction=_INSTRUCTION,
                           objective=objective, gold=gold)
                count += 1
                if limit and count >= limit:
                    return
