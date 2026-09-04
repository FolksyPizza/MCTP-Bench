"""artifact_selection — Category 3 (artifact retrieval).

A question whose answer lives in exactly one configuration file among several. The flat
condition inlines every config file; the mctp condition delivers only the relevant reference
and lets the receiver retrieve that one file. A look-alike distractor (a cache connection
pool of 50) tests whether inlining everything causes the receiver to report the wrong value.

Success: correct value (20) and correct location; retrieves only the relevant artifact.
Failure mode (MISLEADING): reports the cache pool (50) instead of the DB pool (20).
Why ASTP helps: references plus targeted retrieval avoid inlining unrelated files.
"""
from __future__ import annotations

from dataclasses import dataclass

import mctpbench  # noqa: F401
from astp import AstpStore, Provenance


def _p(agent="agent_A", ts=0, source="transcript", conf=1.0):
    return Provenance(source=source, agent=agent, model="model-x", timestamp=ts, confidence=conf)


def build():
    s = AstpStore()

    s.assert_node("task_B", "task",
        "What database connection pool size does the payments service use, and where is it "
        "configured?", _p(ts=1))
    s.assert_node("task_C", "task",
        "Audit non-database service configuration for the payments service.", _p(agent="agent_Z", ts=2))

    # the one relevant file
    s.assert_artifact("art_dbconfig", "config/payments/db.yaml",
        "database:\n  url: postgres://payments-db/payments\n  pool:\n    size: 20   # max DB connections\n"
        "    timeoutMs: 3000\n",
        "yaml", ["database.pool.size"], _p(ts=3))

    # distractors, including a look-alike pool value
    s.assert_artifact("art_cacheconfig", "config/payments/cache.yaml",
        "cache:\n  host: redis://payments-cache\n  connectionPool: 50   # redis connections\n",
        "yaml", ["cache.connectionPool"], _p(agent="agent_Z", ts=4))
    s.assert_artifact("art_logging", "config/payments/logging.yaml",
        "logging:\n  level: INFO\n  sink: stdout\n", "yaml", ["logging.level"], _p(agent="agent_Z", ts=5))
    s.assert_artifact("art_flags", "config/payments/flags.yaml",
        "features:\n  newCheckout: true\n  retries: 3\n", "yaml", ["features"], _p(agent="agent_Z", ts=6))
    s.assert_artifact("art_metrics", "config/payments/metrics.yaml",
        "metrics:\n  exporter: prometheus\n  intervalSec: 15\n", "yaml", ["metrics"], _p(agent="agent_Z", ts=7))
    s.assert_artifact("art_email", "config/payments/email.yaml",
        "email:\n  provider: smtp\n  poolSize: 8\n", "yaml", ["email.poolSize"], _p(agent="agent_Z", ts=8))

    s.assert_node("ent_dbpool", "entity",
        "Connection pool: bounds concurrent connections to a backing service.", _p(ts=9))

    # only the db config is connected to task_B
    s.assert_edge("task_B", "art_dbconfig", "relates_to", _p(ts=10))
    s.assert_edge("art_dbconfig", "ent_dbpool", "derived_from", _p(ts=11))

    # distractors belong to the unrelated audit task
    for i, aid in enumerate(["art_cacheconfig", "art_logging", "art_flags", "art_metrics", "art_email"]):
        s.assert_edge("task_C", aid, "relates_to", _p(agent="agent_Z", ts=12 + i))

    return s, "task_B"


FLAT_TRANSCRIPT = """[AGENT A — payments service configuration dump]

> Question: what database connection pool size does the payments service use, and where?

Here are the payments service config files.

config/payments/db.yaml:
database:
  url: postgres://payments-db/payments
  pool:
    size: 20   # max DB connections
    timeoutMs: 3000

config/payments/cache.yaml:
cache:
  host: redis://payments-cache
  connectionPool: 50   # redis connections

config/payments/logging.yaml:
logging:
  level: INFO
  sink: stdout

config/payments/flags.yaml:
features:
  newCheckout: true
  retries: 3

config/payments/metrics.yaml:
metrics:
  exporter: prometheus
  intervalSec: 15

config/payments/email.yaml:
email:
  provider: smtp
  poolSize: 8
"""


def check(answer: str):
    a = answer.lower()
    crit = {
        "correct_value": "20" in a,
        "correct_location": any(k in a for k in ("db.yaml", "dbconfig", "database.pool", "database:")),
    }
    # MISLEADING: reports the cache connection pool (50) instead of the DB pool (20).
    misleading = "50" in a and "20" not in a
    passed = crit["correct_value"] and crit["correct_location"] and not misleading
    return passed, crit, misleading


@dataclass
class _Scenario:
    name = "artifact_selection"
    check = staticmethod(check)

    @property
    def flat_transcript(self):
        return FLAT_TRANSCRIPT

    def build(self):
        return build()


scenario = _Scenario()
