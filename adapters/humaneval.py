"""HumanEval adapter — function completion with an objective unit-test scorer.

Loads the standard HumanEval JSONL (fields: `task_id`, `prompt`, `canonical_solution`,
`test`, `entry_point`). The dataset file is not vendored; point at it with `ASTP_HUMANEVAL`
or place it at `data/HumanEval.jsonl` (see scripts/fetch_datasets.sh). When neither is present,
a small bundled sample (`data/humaneval_sample.jsonl`) is used so the pipeline runs offline.

HumanEval is a stateless suite: there is no prior-agent context to transfer, so the meaningful
comparison is `transcript` (the plain task) vs `mctp` (the task delivered as a minimal packet)
— a check that structured transfer does not degrade an already well-scoped task. `summary` and
`rag` over empty context coincide with `transcript` and are omitted by default.
"""
from __future__ import annotations

import json
import os

from conditions import Source

from .base import Adapter, Task
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scoring.objective import humaneval_scorer  # noqa: E402

_HERE = os.path.dirname(__file__)
_INSTRUCTION = (
    "Complete the following Python function. Respond with the full function implementation "
    "inside a single ```python code block, including the signature. Do not add explanations."
)


def _dataset_path() -> str:
    env = os.environ.get("ASTP_HUMANEVAL")
    if env and os.path.exists(env):
        return env
    full = os.path.join(_HERE, "..", "data", "HumanEval.jsonl")
    if os.path.exists(full):
        return full
    return os.path.join(_HERE, "..", "data", "humaneval_sample.jsonl")


class HumanEvalAdapter(Adapter):
    name = "humaneval"
    tier = "small"
    default_conditions = ("transcript", "summary", "rag", "mctp")

    def __init__(self, path: str | None = None):
        self.path = path or _dataset_path()

    def tasks(self, limit: int | None = None):
        count = 0
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                p = json.loads(line)
                tid = p["task_id"]
                yield Task(
                    task_id=tid,
                    source=Source(suite=self.name, task_id=tid, task=p["prompt"],
                                  tier=self.tier),
                    receiver_instruction=_INSTRUCTION,
                    objective=humaneval_scorer(p),
                    gold=p.get("canonical_solution", ""),
                    meta={"entry_point": p["entry_point"]},
                )
                count += 1
                if limit and count >= limit:
                    return
