# Scenarios

The benchmark suite has ten scenarios spanning several domains, context sizes, and failure
modes. Each scenario defines a task, a `flat` baseline (the raw Agent-A transcript), and the
`mctp` condition (the Core selector's packet with retrieve-on-demand), plus a keyword-based
gold check. Category numbers refer to [BENCHMARK.md](BENCHMARK.md).

Token counts are tiktoken `o200k_base` totals (context plus any retrieved artifact source) from
the recorded single-trial Claude-subagent runs. "mctp" is the total including retrieval.

| Scenario | Category | Domain | flat | mctp | mctp pass |
|----------|----------|--------|------|------|-----------|
| artifact_selection | 3 artifact retrieval | service config | 184 | 137 | yes |
| hidden_constraint | negative control | data / compliance | 300 | 190 | **no** |
| auth_migration | 2 decision transfer | authentication | 291 | 436 | yes |
| api_versioning | 2 decision transfer | API design | 299 | 278 | yes |
| flaky_test | 1 coding handoff | testing / CI | 386 | 401 | yes |
| cache_staleness | 2 decision transfer | distributed cache | 557 | 529 | yes |
| schema_migration | 4 larger task | databases | 717 | 606 | yes |
| bug43 | 1 coding handoff | distributed systems | 783 | 513 | yes |
| payment_idempotency | 4 larger task | payments | 2319 | 645 | yes |
| outage_investigation | 4 larger task | reliability / caching | 2476 | 828 | yes |

## bug43 (Category 1, coding handoff)
Fix intermittent data loss during partition migration. Correct answer: time-bounded leases;
renew the lease before copying node state. Contains a superseded distributed-locking decision.
ASTP filters the stale decision and references the files to change; the receiver made one
targeted retrieve.

## cache_staleness (Category 2, decision transfer)
Fix stale reads in a distributed cache. Correct answer: write-through invalidation with
versioned keys; the read path compares the version and reloads on mismatch. Contains a
superseded TTL-tuning decision as a misdirection. The receiver answered from the packet, then
made two confirmatory pulls.

## auth_migration (Category 2, decision transfer)
Continue a migration from server-side sessions to stateless JWT. Correct answer: validate a JWT
per request; do not regress to sessions. Contains a superseded session-store decision. This is
the smallest transcript with little to prune, so ASTP was token-worse here (+50%); the receiver
also could not cite the rejected sub-alternative that the flat baseline retained.

## artifact_selection (Category 3, artifact retrieval)
Report the database connection pool size for the payments service and where it is set. Only one
config file is relevant among several; a look-alike distractor (a cache pool of 50 versus the
DB pool of 20) tests whether inlining every file causes a wrong answer. ASTP delivered only the
relevant reference and the receiver made one targeted retrieve; the distractor was never
delivered.

## payment_idempotency (Category 4, larger repository task)
Fix duplicate charges under retries. Correct answer: deduplicate by idempotency key
(putIfAbsent) before charging, atomically. The ~2,300-token transcript inlines several files,
ruled-out suspects, and a benchmark; two approaches (a per-user lock and a timestamp heuristic)
are superseded. This is the clearest ASTP win: total tokens fell 72% at equal correctness.

## schema_migration (Category 4, larger task, hard constraints)
Execute a zero-downtime migration to add a NOT NULL column to a large table. Correct answer:
expand/contract, add the column nullable, backfill in batches, then add the constraint in a
later step; never a single blocking ALTER or a maintenance window. Carries hard constraints (no
downtime, backward compatibility). The receiver got the strategy from the packet and requested
the concrete migration and backfill files.

## api_versioning (Category 2, decision transfer)
Implement authentication for v2 API endpoints. Correct answer: validate a Bearer token from the
Authorization header; do not reintroduce the deprecated URL query-string token, which leaks into
logs and referrers. Contains a superseded query-string-token decision. The packet was sufficient
with no retrieval.

## flaky_test (Category 1, coding handoff)
Fix a flaky test. Correct answer: inject a Clock and control time in the test; the root cause is
a direct Instant.now() call. Two band-aids (an @Retry annotation and a Thread.sleep) are
superseded. The receiver got the fix from the packet and requested the source files to place it.

## outage_investigation (Category 4, larger task, very high token count)
Root-cause and fix a cascading checkout outage. Correct answer: add single-flight / request
coalescing on the cache read path so concurrent misses for a hot key share one origin fetch, and
change the circuit breaker to trip on error rate; not scaling out instances or raising timeouts.
The ~2,500-token transcript inlines several service files, configs, dashboards, a minute-by-
minute log timeline, and ruled-out suspects (thread pool, bulkhead, health checks); two
approaches (scale-out and timeout increase) are superseded. The receiver got the fix from the
packet and requested four referenced files; total tokens fell 67% at equal correctness.

## hidden_constraint (negative control, ASTP expected to underperform)
Add a bulk-delete endpoint for user records. Correct answer: delete via the soft-delete
tombstone path only; hard DELETE is forbidden for GDPR and audit. The constraint is present in
the flat transcript, but in the ASTP graph it was linked to the compliance-review task and never
connected to the bulk-delete task, so the selector's packet omits it, an extraction/linking
miss. Result: the flat condition answered correctly; the mctp condition could not determine the
required deletion path and abstained. This scenario demonstrates that extraction fidelity is the
system's ceiling and that the benchmark can fail ASTP. It also exposes a scoring limitation: a
purely keyword-based check can be fooled by the mere presence of the `softDelete` symbol in the
packet, so this run's outcome is judged on whether the receiver actually committed to the
compliant path.
