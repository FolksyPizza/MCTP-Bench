"""The Source: a task and its transferable prior context, condition-agnostic.

An adapter turns one external task into a Source; the condition builders turn a Source into
the four receiver inputs. A Source may carry its prior context two ways:

- `transcript` / `docs`: plain text — a raw prior-agent transcript and a corpus of retrievable
  documents (id -> full source). Used by suites without a hand-authored graph.
- `graph` / `graph_task_id`: a prebuilt Core MCTP graph and the task node within it. The
  in-house scenarios provide this; the `mctp` condition uses the Core selector over it, and
  the other conditions fall back to `transcript` / `docs`.

Once the extractor exists it will populate `graph` from a real repository, so high-context
suites get a real `mctp` packet rather than the minimal single-task packet used for stateless
tasks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Source:
    suite: str
    task_id: str
    task: str                                   # the instruction/question given to the receiver
    tier: str = "small"                          # small | medium | large | subagent
    transcript: str = ""                         # raw prior-agent context ("" for bare tasks)
    docs: dict = field(default_factory=dict)     # id -> full source (retrievable corpus)
    graph: Any = None                            # optional prebuilt Core MCTP graph
    graph_task_id: str | None = None

    @property
    def has_context(self) -> bool:
        return bool(self.transcript or self.docs or self.graph)


@dataclass
class Built:
    condition: str
    text: str                                   # context handed to the receiver
    retrievable: dict = field(default_factory=dict)   # id -> full source for retrieve-on-demand
    packet_node_ids: list = field(default_factory=list)
    prep_tokens: int = 0                         # summarizer / embedding inference this cost
    meta: dict = field(default_factory=dict)
