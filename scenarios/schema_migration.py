"""schema_migration — Category 4 (larger repository task) with hard constraints.

Agent A planned a zero-downtime migration to add a NOT NULL `region` column to a large
`orders` table. A first attempt (a single blocking ALTER that rewrites the table) is
superseded by an expand/contract migration (add nullable, backfill in batches, then
constrain). The task carries hard constraints: no downtime and backward compatibility during
rollout. The flat transcript is large (DDL, a lock benchmark, batch-job code).

Correct answer: expand/contract — add the column nullable, backfill in batches with an online
job, then add the NOT NULL constraint in a later step; never a single blocking ALTER or a
maintenance window.
Failure mode (MISLEADING): proposing the blocking ALTER or a downtime window.
Why ASTP helps: the transcript is mostly prunable (rejected approaches, full DDL dumps).
"""
from __future__ import annotations

from dataclasses import dataclass

import mctpbench  # noqa: F401
from astp import AstpStore, Provenance


def _p(agent="agent_A", ts=0, source="transcript", conf=1.0):
    return Provenance(source=source, agent=agent, model="model-x", timestamp=ts, confidence=conf)


_MIGRATION = """-- migrations/0047_add_region.sql (DRAFT — do not ship as written)
-- Attempt 1 (rejected): single blocking statement.
ALTER TABLE orders ADD COLUMN region TEXT NOT NULL DEFAULT 'us';
"""

_ORDERS_DDL = """CREATE TABLE orders (
  id           BIGINT PRIMARY KEY,
  user_id      BIGINT NOT NULL,
  total_cents  BIGINT NOT NULL,
  currency     TEXT   NOT NULL,
  status       TEXT   NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);  -- ~840M rows in production
"""

_BACKFILL = """// jobs/BackfillRegion.java
final class BackfillRegion {
  // Backfills `region` in batches by primary-key range, throttled, resumable.
  void run(long fromId, long toId, int batch) {
    for (long id = fromId; id < toId; id += batch) {
      db.exec("UPDATE orders SET region = derive_region(user_id) " +
              "WHERE id >= ? AND id < ? AND region IS NULL", id, id + batch);
      throttle();
    }
  }
}
"""


def build():
    s = AstpStore()

    s.assert_node("task_A", "task",
        "Plan a migration to add a required `region` column to the orders table without "
        "downtime.", _p(ts=1))
    s.assert_node("task_B", "task",
        "Execute the region-column migration on orders. Hard constraints: zero downtime and "
        "backward compatibility for running app versions during the rollout.", _p(ts=2))
    s.assert_node("task_C", "task",
        "Add a Grafana dashboard for order latency.", _p(agent="agent_Z", ts=3))

    s.assert_artifact("art_migration", "migrations/0047_add_region.sql", _MIGRATION,
        "sql", ["0047_add_region"], _p(ts=4))
    s.assert_artifact("art_orders", "db/schema/orders.sql", _ORDERS_DDL,
        "sql", ["orders"], _p(ts=5))
    s.assert_artifact("art_backfill", "jobs/BackfillRegion.java", _BACKFILL,
        "java", ["run(long, long, int)"], _p(ts=6))
    s.assert_artifact("art_dashboard", "ops/dashboards/order_latency.json",
        "{ \"title\": \"Order latency\", \"panels\": [] }\n", "json", ["order_latency"],
        _p(agent="agent_Z", ts=7))

    s.assert_node("art_slo", "artifact",
        "SLO: orders API must stay under 200ms p99 and take zero scheduled downtime; migrations "
        "may not hold table locks longer than 1s.", _p(ts=8))

    s.assert_node("ent_expand_contract", "entity",
        "Expand/contract migration: add a column nullable, backfill data in batches with an "
        "online job, then add the NOT NULL constraint in a later deploy once every row is set.",
        _p(ts=9))
    s.assert_node("ent_online_ddl", "entity",
        "Online DDL: schema changes that avoid a full-table rewrite and long locks.", _p(ts=10))
    s.assert_node("ent_dashboard", "entity",
        "Dashboard panels: time-series queries over the metrics store.", _p(agent="agent_Z", ts=11))

    s.assert_node("dec_blocking_alter", "decision",
        "Add the column with a single ALTER TABLE ... ADD COLUMN region TEXT NOT NULL DEFAULT.",
        _p(ts=12))
    s.assert_node("dec_maintenance", "decision",
        "Take a short maintenance window to run the migration offline.", _p(ts=13))
    s.assert_node("dec_expand_contract", "decision",
        "Use expand/contract: (1) add `region` as nullable with no default; (2) backfill in "
        "batches via BackfillRegion; (3) once fully populated, add the NOT NULL constraint in a "
        "later migration. This holds no long lock and stays backward compatible. Supersedes the "
        "blocking ALTER and the maintenance window.", _p(ts=14, source="tool", conf=0.95))
    s.assert_node("dec_dashboard", "decision",
        "Use a stacked time-series panel for p50/p99.", _p(agent="agent_Z", ts=15))

    s.assert_edge("task_B", "art_migration", "modifies", _p(ts=16))
    s.assert_edge("task_B", "dec_expand_contract", "relates_to", _p(ts=17))
    s.assert_edge("task_B", "art_slo", "relates_to", _p(ts=18))
    s.assert_edge("dec_expand_contract", "ent_expand_contract", "derived_from", _p(ts=19))
    s.assert_edge("dec_expand_contract", "ent_online_ddl", "derived_from", _p(ts=20))
    s.assert_edge("art_migration", "art_orders", "depends_on", _p(ts=21))
    s.assert_edge("dec_expand_contract", "art_backfill", "relates_to", _p(ts=22))

    s.assert_edge("task_A", "dec_blocking_alter", "relates_to", _p(ts=23))
    s.assert_edge("task_A", "dec_maintenance", "relates_to", _p(ts=24))
    s.supersede("dec_blocking_alter", "dec_expand_contract", _p(ts=25, source="tool"))
    s.supersede("dec_maintenance", "dec_expand_contract", _p(ts=26, source="tool"))

    s.assert_edge("task_C", "art_dashboard", "modifies", _p(agent="agent_Z", ts=27))
    s.assert_edge("task_C", "dec_dashboard", "relates_to", _p(agent="agent_Z", ts=28))
    s.assert_edge("art_dashboard", "ent_dashboard", "derived_from", _p(agent="agent_Z", ts=29))

    return s, "task_B"


FLAT_TRANSCRIPT = f"""[AGENT A — raw session log, orders.region migration planning]

> Task: add a required `region` column to `orders` with no downtime.

The table is large and hot.
$ cat db/schema/orders.sql
{_ORDERS_DDL}
~840M rows, and it backs the checkout path. The SLO is strict.
$ cat ops/slo/orders.md
  Orders API must stay under 200ms p99 and take zero scheduled downtime. Migrations may not
  hold table locks longer than 1s.

Attempt 1: just add the column in one statement.
$ cat migrations/0047_add_region.sql
{_MIGRATION}
Let me check what a single ALTER ... ADD COLUMN NOT NULL DEFAULT does on this engine at this
size.
$ ./tools/explain_migration.sh 0047
  ADD COLUMN NOT NULL DEFAULT on 840M rows: full table rewrite, ACCESS EXCLUSIVE lock,
  estimated 22 minutes locked. This blocks all reads and writes to orders.
22 minutes of ACCESS EXCLUSIVE is a hard no — it violates the 1s lock limit and takes the
checkout path down. Rejecting the single blocking ALTER.

Attempt 2: take a maintenance window and run it offline. Talked to the on-call lead — the SLA
with our largest customers forbids scheduled downtime this quarter. Rejecting the maintenance
window.

Attempt 3: expand/contract. This is the standard zero-downtime pattern.
  Step 1 — add the column NULLABLE with no default (this is metadata-only, no rewrite, no long
    lock). App keeps working; new code tolerates NULL region.
  Step 2 — backfill in batches with an online job, throttled and resumable.
$ cat jobs/BackfillRegion.java
{_BACKFILL}
  Step 3 — once every row has a region, add the NOT NULL constraint in a LATER migration
    (validate-then-set, which does not rewrite the table). Only then does the column become
    required.
This holds no long lock, stays backward compatible while both old and new app versions run,
and respects the SLO. Expand/contract is the plan; the blocking ALTER and the maintenance
window are both rejected.

(Unrelated: someone also asked for an order-latency Grafana dashboard — separate task, ignore.)

Handing off. Execute the expand/contract migration; do NOT ship 0047 as written.
"""


def check(answer: str):
    a = answer.lower()
    crit = {
        "expand_contract": ("nullable" in a or "backfill" in a or "batch" in a or "expand" in a
                            or "online" in a or "step" in a or "phase" in a),
        "later_constraint": ("not null" in a or "constraint" in a) and
                            ("later" in a or "then" in a or "after" in a or "separate" in a
                             or "step" in a or "once" in a),
        "rejected_blocking": ("rewrite" in a or "lock" in a or "downtime" in a or "blocking" in a
                             or "maintenance" in a) and ("reject" in a or "not" in a or "avoid" in a
                             or "instead" in a or "no " in a),
    }
    # MISLEADING: recommends the blocking ALTER or a downtime window as the plan.
    misleading = (
        ("maintenance window" in a or "single alter" in a or "add column region text not null default" in a
         or "take downtime" in a)
        and ("backfill" not in a and "expand" not in a and "nullable" not in a)
    )
    passed = crit["expand_contract"] and not misleading
    return passed, crit, misleading


@dataclass
class _Scenario:
    name = "schema_migration"
    check = staticmethod(check)

    @property
    def flat_transcript(self):
        return FLAT_TRANSCRIPT

    def build(self):
        return build()


scenario = _Scenario()
