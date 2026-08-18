"""cache_staleness — a larger scenario, built directly on the Core MCTP API.

Story: Agent A investigates intermittent stale reads from a distributed cache. A's first
decision (bound staleness with a TTL) is SUPERSEDED after benchmarks show TTL only shrinks
the stale window, not the bug. A switches to write-through invalidation with versioned keys
and finds the root cause: the read path never checks the version. Agent B must fix the read
path.

Larger than bug43: more components, two superseded decisions, two irrelevant subsystems, and
a real MISLEADING trap — the abandoned "increase the TTL" approach, which a flat transcript
carries and MCTP filters via the supersede edge.
"""
from __future__ import annotations

from dataclasses import dataclass

import mctpbench  # noqa: F401  (sys.path bootstrap to Core MCTP)
from mctp import MCTPStore, Provenance


def _p(agent="agent_A", ts=0, source="transcript", conf=1.0):
    return Provenance(source=source, agent=agent, model="model-x", timestamp=ts, confidence=conf)


def build():
    s = MCTPStore()

    # --- tasks ---
    s.assert_node("task_A", "task",
        "Investigate intermittent stale reads from the distributed cache: readers see values "
        "tens of seconds out of date after a write, under normal load.", _p(ts=1))
    s.assert_node("task_B", "task",
        "Fix stale reads in the distributed cache read path.", _p(ts=2))
    s.assert_node("task_C", "task",
        "Add p99 latency metrics export to the cache layer.", _p(agent="agent_Z", ts=3))

    # --- code artifacts (real source via references) ---
    s.assert_artifact("art_cacheclient", "src/cache/CacheClient.java",
        "public final class CacheClient {\n"
        "  private final Store store; private final VersionStore versions;\n"
        "  public V get(K key) {\n"
        "    Entry e = store.lookup(key);\n"
        "    if (e != null) return e.value;   // BUG: returns cached value without version check\n"
        "    return reload(key);\n"
        "  }\n"
        "  private V reload(K key) { /* fetch from source of truth, cache, return */ }\n"
        "}\n",
        "java", ["get(K)", "reload(K)"], _p(ts=4))
    s.assert_artifact("art_versionstore", "src/cache/VersionStore.java",
        "public final class VersionStore {\n"
        "  public long currentVersion(K key) { ... }   // monotonic, bumped on every write\n"
        "}\n",
        "java", ["currentVersion(K)"], _p(ts=5))
    s.assert_artifact("art_invalidationbus", "src/cache/InvalidationBus.java",
        "public final class InvalidationBus {\n"
        "  public void publish(K key) { ... }   // writers call on every write\n"
        "}\n",
        "java", ["publish(K)"], _p(ts=6))
    s.assert_artifact("art_metrics", "src/cache/MetricsExporter.java",
        "public final class MetricsExporter { void exportP99() { /* histogram */ } }\n",
        "java", ["exportP99()"], _p(agent="agent_Z", ts=7))

    # --- evidence ---
    s.assert_node("art_bug", "artifact",
        "Bug report: after a write, some readers observe the previous value for up to ~60s. "
        "Reproduces under normal load; independent of key size.", _p(ts=8))

    # --- entities ---
    s.assert_node("ent_version", "entity",
        "Versioned-key model: each key has a monotonic version bumped on write; a cached "
        "entry is valid only if its version matches the store's current version.", _p(ts=9))
    s.assert_node("ent_invalidation", "entity",
        "Write-through invalidation: writers synchronously bump the version / publish an "
        "invalidation on every write, so caches can detect staleness immediately.", _p(ts=10))
    s.assert_node("ent_metrics", "entity",
        "Histogram export: p99 computed from a rolling latency histogram.", _p(agent="agent_Z", ts=11))

    # --- decisions ---
    s.assert_node("dec_ttl", "decision",
        "Bound staleness with a 60s TTL on cache entries.", _p(ts=12))
    s.assert_node("dec_writethrough", "decision",
        "Replace TTL with write-through invalidation using versioned keys. Reason: lowering "
        "the TTL only shrinks the stale window and raises miss rate; the stale-read bug "
        "persists at any TTL. Evidence: bench/ttl_vs_version.json.", _p(ts=13, source="tool", conf=0.9))
    s.assert_node("dec_readcheck", "decision",
        "On read, CacheClient.get() must compare the entry's version to "
        "VersionStore.currentVersion(key); on mismatch, treat it as a miss and reload. Root "
        "cause of the stale reads: the read path never validated the version.", _p(ts=14, source="tool", conf=0.95))
    s.assert_node("dec_metrics", "decision",
        "Export p99 via a rolling histogram sampled every 5s.", _p(agent="agent_Z", ts=15))

    # --- relations (relevant cluster around task_B) ---
    s.assert_edge("task_B", "art_cacheclient", "modifies", _p(ts=16))
    s.assert_edge("task_B", "dec_writethrough", "relates_to", _p(ts=17))
    s.assert_edge("task_B", "dec_readcheck", "relates_to", _p(ts=18))
    s.assert_edge("task_B", "art_bug", "relates_to", _p(ts=19))
    s.assert_edge("art_cacheclient", "art_versionstore", "depends_on", _p(ts=20))
    s.assert_edge("art_cacheclient", "art_invalidationbus", "depends_on", _p(ts=21))
    s.assert_edge("art_versionstore", "ent_version", "derived_from", _p(ts=22))
    s.assert_edge("art_invalidationbus", "ent_invalidation", "derived_from", _p(ts=23))
    s.assert_edge("art_bug", "dec_readcheck", "relates_to", _p(ts=24))

    # A's original TTL decision, later superseded
    s.assert_edge("task_A", "dec_ttl", "relates_to", _p(ts=25))
    s.supersede("dec_ttl", "dec_writethrough", _p(ts=26, source="tool"))

    # irrelevant subsystem (must not reach task_B)
    s.assert_edge("task_C", "art_metrics", "modifies", _p(agent="agent_Z", ts=27))
    s.assert_edge("task_C", "dec_metrics", "relates_to", _p(agent="agent_Z", ts=28))
    s.assert_edge("art_metrics", "ent_metrics", "derived_from", _p(agent="agent_Z", ts=29))

    return s, "task_B"


FLAT_TRANSCRIPT = """[AGENT A — raw session log, distributed cache stale-read investigation]

> Task: readers intermittently see stale values from the cache (bug). Investigate.

$ cat reports/stale-reads.md
  After a write, some readers observe the previous value for up to ~60s. Reproduces under
  normal load; independent of key size.

Let me look at the read path.
$ sed -n '1,60p' src/cache/CacheClient.java
  public final class CacheClient {
    private final Store store; private final VersionStore versions;
    public V get(K key) {
      Entry e = store.lookup(key);
      if (e != null) return e.value;   // returns cached value, no version check
      return reload(key);
    }
    private V reload(K key) { /* fetch from source of truth, cache, return */ }
  }

First idea: bound staleness with a TTL. If entries expire after 60s, stale reads can't last
longer than that. Let me just set a 60s TTL and see. Benchmarked TTL variations.
$ ./bench/run.sh ttl_vs_version
  {
    "ttl_60s":  { "stale_reads": 41, "miss_rate": 0.06 },
    "ttl_5s":   { "stale_reads": 39, "miss_rate": 0.28 },
    "versioned":{ "stale_reads": 0,  "miss_rate": 0.07 }
  }
TTL is a dead end: lowering it barely reduces stale reads and blows up the miss rate. The
bug is that reads never notice a write happened — TTL only shrinks the window. Rejecting TTL.

Second approach: write-through invalidation with versioned keys. VersionStore already tracks
a monotonic version per key, bumped on every write; InvalidationBus.publish(key) is called by
writers. So a cached entry is only valid if its version matches VersionStore.currentVersion(key).

Root cause + fix: CacheClient.get() returns the cached value WITHOUT checking the version.
Fix: on read, compare the entry's version to VersionStore.currentVersion(key); on mismatch,
treat it as a miss and reload. That closes the staleness entirely (versioned: 0 stale reads).

Relevant files: CacheClient.java (read path), VersionStore.java (currentVersion), Invalidation
Bus.java (publish on write).

(Unrelated side task: also scoped p99 metrics export for the cache — rolling histogram sampled
every 5s via MetricsExporter. Ignore for the stale-read bug.)

Handing off. Someone implement the version check in CacheClient.get().
"""


def check(answer: str):
    a = answer.lower()
    crit = {
        "mechanism_versioned": ("version" in a)
        and ("invalidat" in a or "write-through" in a or "write through" in a),
        "read_version_check": ("version" in a)
        and ("mismatch" in a or "compare" in a or "reload" in a or "check" in a or "match" in a),
        "rejected_ttl": ("ttl" in a)
        and ("reject" in a or "instead" in a or "replace" in a or "not" in a
             or "dead end" in a or "insufficient" in a or "only" in a),
    }
    # MISLEADING: proposes TTL tuning AS the fix, without the versioned mechanism.
    misleading = (
        any(p in a for p in ("increase the ttl", "raise the ttl", "lower the ttl",
                             "shorter ttl", "tune the ttl", "reduce the ttl", "set the ttl"))
        and "version" not in a
    )
    passed = crit["mechanism_versioned"] and crit["read_version_check"] and not misleading
    return passed, crit, misleading


@dataclass
class _Scenario:
    name = "cache_staleness"
    check = staticmethod(check)

    @property
    def flat_transcript(self):
        return FLAT_TRANSCRIPT

    def build(self):
        return build()


scenario = _Scenario()
