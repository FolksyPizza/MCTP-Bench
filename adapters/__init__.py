"""Suite adapters: an external benchmark -> MCTP-Bench tasks.

An adapter turns one suite into a stream of `Task`s. Each task carries the `Source` the four
conditions build from, the receiver instruction for that suite, an optional objective scorer
(unit tests / exact match), and a gold answer or rubric for the later judge pass.

    get_adapter(name) -> Adapter
    adapter.tasks(limit=None) -> Iterable[Task]

Implemented: `humaneval` (code, objective unit-test scorer) and `inhouse` (the ten control
scenarios). SWE-bench and long-context suites are added once the extractor exists.
"""
from __future__ import annotations

from .base import Adapter, Task


def get_adapter(name: str) -> Adapter:
    if name == "humaneval":
        from .humaneval import HumanEvalAdapter
        return HumanEvalAdapter()
    if name == "inhouse":
        from .inhouse import InHouseAdapter
        return InHouseAdapter()
    raise ValueError(f"unknown suite: {name} (have: humaneval, inhouse)")


__all__ = ["Adapter", "Task", "get_adapter"]
