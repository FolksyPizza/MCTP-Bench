# bug43 — verbatim Agent B outputs

Runner: isolated Claude subagent, given only its context and an identical neutral question.
One trial per condition. See `MCTP/docs/EXPERIMENTS.md` for methodology.

---

## Condition FLAT (raw transcript, 783 tok, 0 pulls) — PASS

```
1. Ownership mechanism NodeTransfer should use to fix bug #43: A time-bounded lease via LeaseManager — the destination shard renews the lease before copying, letting the stale owner's lease lapse so it stops accepting writes.

2. The precise ordering constraint (what must happen before what): `leases.renew(pid, ttl)` on the destination must happen BEFORE `copyNodeState(pid, from)`. Current buggy order is copy-then-set-owner; the fix is renew-lease-then-copy.

3. Any alternative approach that was considered and rejected, and why: Distributed locking (a cluster-wide lock around migrate()) was rejected — benchmarks showed heavy contention under load, p99 blowing up to 4.2s and 37 stalled migrations, versus the lease approach's p99 of 140ms and 0 stalls.

4. Anything missing that you'd need to look up: exact TTL/Duration value; how the stale owner's lease is made to lapse; whether the write path checks isOwner; renew's exact signature.
```

## Condition MCTP (reference packet, 420 tok) — round 1, PASS + targeted retrieve

```
1. Ownership mechanism: time-bounded lease (dec_leases) — renew via `leases.renew(pid, ...)`, guarded by `leases.isOwner(pid)`, instead of distributed locking.
2. Ordering constraint: the lease must be renewed/confirmed BEFORE `copyNodeState` runs. Change goes in `migrate(PartitionId, ShardId)` in src/shard/NodeTransfer.java.
3. Alternative rejected: distributed locking — lock contention stalled migrations under load (bench/lock_vs_lease.json).
4. Nothing critical for the strategy, but to write the exact patch confidently I'd want the full source of NodeTransfer.migrate.

RETRIEVE art_nodetransfer
```

## Condition MCTP — round 2 (after retrieve fulfilled with real source) — final, PASS

```
Concrete patch to migrate():
  void migrate(PartitionId pid, ShardId from) {
    Owner owner = map.ownerOf(pid);
-   copyNodeState(pid, from);      // BUG: copies BEFORE confirming ownership
-   map.setOwner(pid, self);
+   leases.renew(pid, LEASE_DURATION);
+   map.setOwner(pid, self);
+   if (!leases.isOwner(pid)) { throw new MigrationAbortedException(pid); }
+   copyNodeState(pid, from);       // now safe: no concurrent writes lost
  }
Nothing missing — implementable confidently.
```

The round-1 request for full source is the intended retrieve-on-demand behavior: a precise,
targeted pull rather than the vague gap produced by summary-only artifacts (PLAN.md §8.6.2).
