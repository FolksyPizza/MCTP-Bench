"""The adapter contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conditions import Source  # noqa: E402


# An objective scorer maps the receiver's answer text to (pass, detail). None when the suite
# has no programmatic scorer (open-ended tasks are left for the judge pass).
Objective = Optional[Callable[[str], "tuple[bool, dict]"]]


@dataclass
class Task:
    task_id: str
    source: Source
    receiver_instruction: str            # the question/prompt handed to the receiver
    objective: Objective = None
    gold: str = ""                       # reference answer or rubric (for the judge pass)
    reasoning_expected: bool = False
    meta: dict = field(default_factory=dict)


class Adapter:
    """Base class. Subclasses set `name`, `tier`, and implement `tasks`."""
    name = "adapter"
    tier = "small"
    default_conditions = ("transcript", "summary", "rag", "mctp")

    def tasks(self, limit: int | None = None) -> Iterable[Task]:
        raise NotImplementedError
