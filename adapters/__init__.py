"""Suite adapters: an external benchmark -> MCTP-Bench tasks.

An adapter turns one suite into a stream of `Task`s. Each task carries the `Source` the four
conditions build from, the receiver instruction for that suite, an optional objective scorer
(unit tests / exact match), and a gold answer or rubric for the later judge pass.

    get_adapter(name) -> Adapter
    adapter.tasks(limit=None) -> Iterable[Task]

Implemented: `humaneval` and `mbpp` (code, objective unit-test scorers), `gsm8k` (math,
exact-match scorer), and `inhouse` (the ten control scenarios). SWE-bench and long-context
suites are added once the extractor exists.
"""
from __future__ import annotations

from .base import Adapter, Task


def get_adapter(name: str) -> Adapter:
    if name == "humaneval":
        from .humaneval import HumanEvalAdapter
        return HumanEvalAdapter()
    if name == "mbpp":
        from .mbpp import MBPPAdapter
        return MBPPAdapter()
    if name == "gsm8k":
        from .gsm8k import GSM8KAdapter
        return GSM8KAdapter()
    if name == "swebench":
        from .swebench import SWEBenchAdapter
        return SWEBenchAdapter()
    if name == "repobench":
        from .repobench import RepoBenchAdapter
        return RepoBenchAdapter()
    if name == "longbench":
        from .longbench import LongBenchAdapter
        return LongBenchAdapter()
    if name == "multifile":
        from .multifile import MultiFileAdapter
        return MultiFileAdapter()
    if name == "inhouse":
        from .inhouse import InHouseAdapter
        return InHouseAdapter()
    if name == "swarm":
        from .swarm import SwarmAdapter
        return SwarmAdapter()
    raise ValueError(f"unknown suite: {name} (have: humaneval, mbpp, gsm8k, swebench, "
                     f"repobench, longbench, inhouse, swarm)")


__all__ = ["Adapter", "Task", "get_adapter"]
