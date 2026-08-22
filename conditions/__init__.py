"""Condition builders: one Source -> the receiver's input, four ways.

Each builder takes the same `Source` (a task plus its transferable prior context) and produces
a `Built` (the context text handed to the receiver, plus any retrievable artifact map and the
preparation cost the condition incurred). This is where transcript / summary / rag / mctp
differ; everything downstream (runner, scoring, recording) is identical across conditions.

    transcript  the raw prior-agent context, inline and unfiltered (the baseline)
    summary     the same receiver model condenses the prior context into a handoff
    rag         the prior context is chunked and lexically retrieved for the task
    mctp        the Core selector packet (explicit state + artifact references) + retrieve

`mctp-learned` is added once the reranker exists. When a task carries no prior context
(a stateless suite such as HumanEval) the four conditions coincide, which is the intended
Phase-0 pipeline check rather than a transfer comparison.
"""
from __future__ import annotations

from .source import Built, Source
from .builders import build, CONDITIONS

__all__ = ["Built", "Source", "build", "CONDITIONS"]
