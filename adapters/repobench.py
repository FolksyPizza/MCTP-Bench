"""RepoBench adapter — cross-file next-line code completion (high context).

Each record is a repository snapshot plus an in-progress file; the receiver must predict the
next line of code, which typically depends on symbols defined in other files. The extractor
turns the repo into ASTP state (so the `mctp` condition can transfer the relevant cross-file
context), while `transcript` dumps the files and `rag` retrieves over them.

Record fields: `task_id`, `files` (path -> content), `target_file`, `prefix` (the target file's
content up to the cursor), `gold_line` (the next line). Point at the dataset with
`ASTP_REPOBENCH` or `data/repobench.jsonl`; a bundled sample runs offline. The objective scorer
is a whitespace-insensitive match of the predicted line to the gold line.
"""
from __future__ import annotations

import json
import os
import sys

from .base import Adapter, Task, source_from_repo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scoring.objective import line_match  # noqa: E402

_HERE = os.path.dirname(__file__)
_INSTRUCTION = (
    "Predict the single next line of code that should follow the in-progress file below, using "
    "the repository context. Respond with just that one line inside a ```python code block."
)


def _path() -> str:
    env = os.environ.get("ASTP_REPOBENCH")
    if env and os.path.exists(env):
        return env
    full = os.path.join(_HERE, "..", "data", "repobench.jsonl")
    return full if os.path.exists(full) else os.path.join(_HERE, "..", "data",
                                                          "repobench_sample.jsonl")


class RepoBenchAdapter(Adapter):
    name = "repobench"
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
                tid = p["task_id"]
                task_text = (f"Complete the next line in {p['target_file']}. "
                             f"Code so far:\n{p['prefix']}")
                src = source_from_repo(self.name, tid, task_text, p["files"], tier=self.tier)
                yield Task(
                    task_id=tid, source=src, receiver_instruction=_INSTRUCTION,
                    objective=line_match(p["gold_line"]), gold=p["gold_line"],
                    meta={"target_file": p["target_file"]},
                )
                count += 1
                if limit and count >= limit:
                    return
