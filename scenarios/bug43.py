"""bug43 scenario — reuses the shared ASTP Folia handoff scenario + gold checker.

The ASTP graph builder and the raw baseline transcript live in the ASTP repo (ASTP_HOME);
this file only adds the benchmark-side gold criteria.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import mctpbench  # sets up sys.path to ASTP_HOME (core + bench)
from scenario import build_scenario  # from $ASTP_HOME/bench/scenario.py


def _flat_transcript() -> str:
    path = os.path.join(mctpbench.ASTP_HOME, "bench", "handoff", "baseline_transcript.txt")
    with open(path) as f:
        return f.read()


def check(answer: str):
    """Heuristic gold check for bug #43. Returns (passed, criteria, misleading)."""
    a = answer.lower()
    crit = {
        "mechanism_leases": "lease" in a and ("renew" in a or "time-bounded" in a),
        "ordering_before_copy": "before" in a and ("cop" in a),
        "rejected_locking": ("distributed lock" in a or "locking" in a)
        and ("reject" in a or "instead" in a or "contention" in a or "rejected" in a),
    }
    # MISLEADING: recommends locking as the FIX (the stale/superseded approach) with no lease.
    misleading = (
        any(p in a for p in ("use distributed lock", "add a distributed lock",
                             "acquire a distributed lock", "should use distributed lock"))
        and "lease" not in a
    )
    passed = all(crit.values()) and not misleading
    return passed, crit, misleading


@dataclass
class _Scenario:
    name = "bug43"
    check = staticmethod(check)

    @property
    def flat_transcript(self):
        return _flat_transcript()

    def build(self):
        return build_scenario()


scenario = _Scenario()
