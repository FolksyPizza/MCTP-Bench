"""In-house adapter — the ten control scenarios as benchmark tasks.

Each scenario provides a hand-authored Core ASTP graph and a raw baseline transcript, so all
four conditions are meaningful (there is real prior context to transfer). The scenario's own
`check()` is the objective scorer here; it is the keyword check the ensemble judge is meant to
replace, so these objective passes should be read alongside the judge pass, not instead of it.
"""
from __future__ import annotations

import os
import sys

from conditions import Source

from .base import Adapter, Task

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_HERE, "..", "scenarios"))

import mctpbench  # noqa: E402  (sets up ASTP_HOME on sys.path)
from mctpbench.runner import DEFAULT_QUESTION  # noqa: E402


def _load_scenarios() -> list:
    from bug43 import scenario as bug43
    from cache_staleness import scenario as cache_staleness
    from auth_migration import scenario as auth_migration
    from artifact_selection import scenario as artifact_selection
    from payment_idempotency import scenario as payment_idempotency
    from schema_migration import scenario as schema_migration
    from api_versioning import scenario as api_versioning
    from flaky_test import scenario as flaky_test
    from hidden_constraint import scenario as hidden_constraint
    from outage_investigation import scenario as outage_investigation
    return [bug43, cache_staleness, auth_migration, artifact_selection, payment_idempotency,
            schema_migration, api_versioning, flaky_test, hidden_constraint,
            outage_investigation]


def _objective(scenario):
    def score(answer: str) -> tuple:
        passed, criteria, misleading = scenario.check(answer)
        return passed, {"criteria": criteria, "misleading": misleading}
    return score


class InHouseAdapter(Adapter):
    name = "inhouse"
    tier = "medium"
    default_conditions = ("transcript", "summary", "rag", "mctp")

    def tasks(self, limit: int | None = None):
        scenarios = _load_scenarios()
        if limit:
            scenarios = scenarios[:limit]
        for scn in scenarios:
            store, task_id = scn.build()
            graph = store.materialize()
            task_text = graph.nodes[task_id].content
            yield Task(
                task_id=scn.name,
                source=Source(suite=self.name, task_id=scn.name, task=task_text,
                              tier=self.tier, transcript=scn.flat_transcript,
                              graph=graph, graph_task_id=task_id),
                receiver_instruction=DEFAULT_QUESTION,
                objective=_objective(scn),
                gold=task_text,
            )
