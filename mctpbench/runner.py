"""Agent runners — the seam where an "Agent B" produces an answer from a context.

`AgentRunner.run(task, context, retrievable)` returns a RunResult. `retrievable` maps
artifact-id -> full source for retrieve-on-demand; a runner that emits `RETRIEVE <id>` (or
otherwise decides it needs an artifact) gets it counted as a pull.

- `MockRunner` is deterministic and model-free: it validates the harness end-to-end (CI,
  plumbing) but is NOT an efficacy measurement.
- Real model-in-the-loop runs come from `record_run()` (see harness), which logs an episode
  from an answer obtained out-of-band (e.g. via the Claude Agent tool or an API call).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunResult:
    answer: str
    retrieved_ids: list = field(default_factory=list)
    codebase_reads: int = 0


class MockRunner:
    """Deterministic, scenario-agnostic plumbing stand-in. It "reads" the delivered context
    (echoing it as the answer) and models retrieve-on-demand: if the packet gives artifact
    *references* but no inlined source (`RETRIEVE ` present, no `class ` body), it pulls the
    primary code artifact before answering.

    NOTE: its correctness score is TRIVIAL (it echoes the context, which contains the facts)
    and is NOT an efficacy claim — it validates token accounting, retrieve mechanics, and
    episode logging. Real correctness signal comes from a model runner (Agent tool / API)."""

    name = "mock"

    def run(self, task: str, context: str, retrievable: dict) -> RunResult:
        retrieved = []
        only_references = "RETRIEVE " in context and "class " not in context
        if only_references and retrievable:
            # pull the largest referenced artifact (proxy for "the primary code file")
            aid = max(retrievable, key=lambda k: len(retrievable[k]))
            retrieved.append(aid)
            context += f"\n\n[RETRIEVED {aid}]\n{retrievable[aid]}"
        return RunResult(answer=context, retrieved_ids=retrieved)
