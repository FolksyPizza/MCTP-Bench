# schema_migration — verbatim Agent B outputs

Runner: isolated Claude subagent, one trial per condition. See the MCTP experiment record.

## Condition FLAT (717 tok, 0 pulls) — PASS
```
1. Expand/contract: add `region` nullable, backfill online in batches, then add NOT NULL in a later migration. Do NOT ship 0047 as written.
2. Step 1 add nullable (metadata-only, no rewrite/long lock); Step 2 batched, throttled, resumable backfill by primary-key range; Step 3 add NOT NULL later via validate-then-set. Respects the 200ms p99 / zero-downtime / 1s-lock SLO.
3. Rejected: single blocking ALTER ... NOT NULL DEFAULT (full rewrite, ~22 min ACCESS EXCLUSIVE lock); maintenance window (SLA forbids scheduled downtime).
4. Nothing — sufficient.
```

## Condition MCTP (379 tok upfront) — PASS, 3 pulls
```
1. Expand/contract (online DDL): add `region` nullable, backfill in batches, then add NOT NULL later [dec_expand_contract].
2. (a) add nullable no-default (metadata-only, backward compatible); (b) backfill in batches via BackfillRegion; (c) add NOT NULL in a separate later deploy. Within the SLO.
3. A single blocking ALTER and a maintenance window were considered and rejected — the decision explicitly supersedes them (long lock / scheduled downtime violate the constraints).
4. Would retrieve [art_migration], [art_backfill], [art_orders] for the concrete SQL, batch parameters, and NOT NULL sequencing.
```

Both correct. The mctp agent got the strategy from the packet and requested the concrete files.
