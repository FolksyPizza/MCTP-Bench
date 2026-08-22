"""GSM8K adapter — grade-school math word problems with an exact-match scorer.

Loads the GSM8K JSONL (fields: `question`, `answer`, where `answer` ends in '#### <number>').
Point at it with `MCTP_GSM8K` or place it at `data/gsm8k.jsonl`; a small bundled sample is used
otherwise. Stateless suite: `transcript` vs `mctp`. The scorer compares the final numeric answer.
"""
from __future__ import annotations

import json
import os
import sys

from conditions import Source

from .base import Adapter, Task

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scoring.objective import gsm8k_scorer  # noqa: E402

_HERE = os.path.dirname(__file__)
_INSTRUCTION = (
    "Solve the math word problem below. Show brief reasoning, then end with a line of the form "
    "'#### <final number>'."
)


def _path() -> str:
    env = os.environ.get("MCTP_GSM8K")
    if env and os.path.exists(env):
        return env
    full = os.path.join(_HERE, "..", "data", "gsm8k.jsonl")
    return full if os.path.exists(full) else os.path.join(_HERE, "..", "data", "gsm8k_sample.jsonl")


class GSM8KAdapter(Adapter):
    name = "gsm8k"
    tier = "low"
    default_conditions = ("transcript", "mctp")

    def __init__(self, path: str | None = None):
        self.path = path or _path()

    def tasks(self, limit: int | None = None):
        count = 0
        with open(self.path) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                p = json.loads(line)
                tid = f"gsm8k/{i}"
                yield Task(
                    task_id=tid,
                    source=Source(suite=self.name, task_id=tid, task=p["question"],
                                  tier=self.tier),
                    receiver_instruction=_INSTRUCTION,
                    objective=gsm8k_scorer(p),
                    gold=p["answer"],
                )
                count += 1
                if limit and count >= limit:
                    return
