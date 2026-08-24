"""MBPP adapter — short Python tasks with an objective unit-test scorer.

Loads the MBPP JSONL (fields: `task_id`, `text`, `code`, `test_list`, optional
`test_setup_code`). Point at it with `MCTP_MBPP` or place it at `data/mbpp.jsonl`; a small
bundled sample is used otherwise. Like HumanEval this is a stateless suite, so the meaningful
comparison is `transcript` vs `mctp`.
"""
from __future__ import annotations

import json
import os
import sys

from conditions import Source

from .base import Adapter, Task

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scoring.objective import mbpp_scorer  # noqa: E402

_HERE = os.path.dirname(__file__)
_INSTRUCTION = (
    "Write a Python function that solves the task below. Respond with the function inside a "
    "single ```python code block, defining exactly the name the tests call. No explanations."
)


def _path() -> str:
    env = os.environ.get("MCTP_MBPP")
    if env and os.path.exists(env):
        return env
    full = os.path.join(_HERE, "..", "data", "mbpp.jsonl")
    return full if os.path.exists(full) else os.path.join(_HERE, "..", "data", "mbpp_sample.jsonl")


class MBPPAdapter(Adapter):
    name = "mbpp"
    tier = "low"
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
                tid = f"mbpp/{p['task_id']}"
                # Give the receiver the description plus one example assert to pin the signature.
                task_text = p["text"] + "\n\nExample:\n" + (p["test_list"][0] if p["test_list"]
                                                            else "")
                yield Task(
                    task_id=tid,
                    source=Source(suite=self.name, task_id=tid, task=task_text, tier=self.tier),
                    receiver_instruction=_INSTRUCTION,
                    objective=mbpp_scorer(p),
                    gold=p.get("code", ""),
                )
                count += 1
                if limit and count >= limit:
                    return
