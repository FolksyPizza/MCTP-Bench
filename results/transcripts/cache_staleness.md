# cache_staleness — verbatim Agent B outputs

Runner: isolated Claude subagent, given only its context and an identical neutral question.
One trial per condition. See `MCTP/docs/EXPERIMENTS.md` for methodology.

---

## Condition FLAT (raw transcript, 557 tok, 0 pulls) — PASS, not misled by TTL

```
1. Mechanism: Write-through invalidation using per-key versioning — validate a cached entry against the authoritative monotonic version before returning it, treating any mismatch as a miss.

2. Read-path change: In `CacheClient.get()`, after `store.lookup(key)` returns non-null `Entry e`, compare `e`'s version to `VersionStore.currentVersion(key)`; if they differ, do not return `e.value` — fall through to `reload(key)` instead of the current unconditional `return e.value`.

3. Alternative rejected: A TTL-based approach (60s, 5s) was rejected — it only shrinks the staleness window rather than detecting writes; lowering TTL barely reduced stale reads while sharply raising miss rate (0.06 → 0.28). Versioned gave 0 stale reads at miss rate 0.07.

4. Missing: whether `Entry` stores the version it was cached at; exact `VersionStore.currentVersion(key)` signature. InvalidationBus.publish is writer-side, not needed for the read-path change.
```

## Condition MCTP (reference packet, 417 tok) — PASS from references, then 2 confirmatory pulls

```
1. Mechanism: Replace TTL-based expiry with write-through invalidation using versioned keys. Each key carries a monotonic version bumped on every write; a cached entry is valid only when its version matches the store's current version.

2. Read-path change: In CacheClient.get(K), after locating a cached entry, compare the entry's stored version against VersionStore.currentVersion(key). On mismatch (or absent entry), treat as a miss and call reload(K). Root cause: get() never validated the version.

3. Alternative rejected: Lowering the TTL was rejected — it only shrinks the stale window and raises miss rate while the bug persists at any TTL (evidence: bench/ttl_vs_version.json).

4. I need the full source of CacheClient.java (how entries store/expose version, get()/reload() structure) and VersionStore.java (currentVersion(K) signature).

RETRIEVE art_cacheclient art_versionstore
```

The MCTP agent produced a complete, correct answer (items 1–3) from the references before
retrieving; the two pulls were confirmatory rather than necessary. This receiver-side
over-retrieval reduces the total-token advantage (529 versus 557, a 5.0% reduction) even
though the packet alone was sufficient. See `MCTP/docs/EXPERIMENTS.md`, finding 3.
