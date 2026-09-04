"""outage_investigation — Category 4 (larger repository task), very high token count.

A cascading checkout outage: on cache expiry, concurrent requests for the same key all miss and
stampede the origin (thundering herd); the origin slows; a naive circuit breaker that trips on
consecutive failures never opens; retries pile up into a retry storm. The flat transcript is
large (~5k tokens): multiple full file dumps, configs, dashboards, and logs.

Correct fix: single-flight / request coalescing on the cache read path so concurrent misses for
one key trigger a single origin fetch, and change the circuit breaker to trip on error rate.
Rejected approaches: scale out instances (masks it), and raise timeouts (makes the storm worse).
"""
from __future__ import annotations

from dataclasses import dataclass

import mctpbench  # noqa: F401
from astp import AstpStore, Provenance


def _p(agent="agent_A", ts=0, source="transcript", conf=1.0):
    return Provenance(source=source, agent=agent, model="model-x", timestamp=ts, confidence=conf)


_CACHEREAD = """public final class CacheReadPath {
  private final Cache cache; private final OriginClient origin;
  // Hot path: called per request to resolve a product by id.
  Product get(ProductId id) {
    Product p = cache.get(id);
    if (p != null) return p;
    // MISS: every concurrent caller that misses goes straight to the origin.
    Product fresh = origin.fetch(id);   // no coalescing; N misses -> N origin calls
    cache.put(id, fresh, TTL);
    return fresh;
  }
}
"""

_ORIGIN = """public final class OriginClient {
  private final Http http; private final CircuitBreaker breaker; private final RetryPolicy retry;
  Product fetch(ProductId id) {
    return retry.call(() -> breaker.call(() -> parse(http.get(\"/product/\" + id))));
  }
}
"""

_BREAKER = """public final class CircuitBreaker {
  private int consecutiveFailures = 0;
  // Trips only after N consecutive failures; a steady error rate under load never trips it.
  <T> T call(Supplier<T> op) {
    if (consecutiveFailures >= 20) throw new CircuitOpen();
    try { T r = op.get(); consecutiveFailures = 0; return r; }
    catch (Exception e) { consecutiveFailures++; throw e; }
  }
}
"""

_RETRY = """public final class RetryPolicy {
  int maxAttempts() { return 3; }
  Duration backoff(int attempt) { return Duration.ofMillis(50L * attempt); }
  // On a slow origin, every request spawns up to 3 attempts -> load multiplies under stress.
}
"""

_PRODUCTSVC = """public final class ProductService {
  private final CacheReadPath reads;
  Product product(ProductId id) { return reads.get(id); }   // checkout calls this per line item
}
"""

_LBCONF = """# infra/lb.yaml
upstreams:
  origin:
    hosts: [origin-a, origin-b, origin-c]
    connect_timeout_ms: 200
    read_timeout_ms: 800
    max_conns_per_host: 256
"""

_THREADPOOL = """public final class ThreadPool {
  int core() { return 64; }
  int max() { return 512; }
  Duration keepAlive() { return Duration.ofSeconds(60); }
}
"""

_BULKHEAD = """public final class Bulkhead {
  // Per-dependency concurrency cap; currently NOT applied to the origin client.
  int limit(String dep) { return dep.equals("origin") ? Integer.MAX_VALUE : 32; }
}
"""

_DASHBOARD = """{ "title": "Origin health",
  "panels": [ {"metric": "origin_qps"}, {"metric": "origin_p99_ms"},
              {"metric": "origin_inflight"}, {"metric": "breaker_state"} ] }
"""


def build():
    s = AstpStore()

    s.assert_node("task_A", "task",
        "Root-cause the checkout outage on 03-14: p99 exploded and the origin saturated during "
        "a traffic spike; investigate.", _p(ts=1))
    s.assert_node("task_B", "task",
        "Fix the checkout outage: stop the cache stampede and retry storm that saturate the "
        "origin when a hot key expires.", _p(ts=2))
    s.assert_node("task_C", "task",
        "Refresh the marketing banner copy on the homepage.", _p(agent="agent_Z", ts=3))

    s.assert_artifact("art_cacheread", "src/catalog/CacheReadPath.java", _CACHEREAD,
        "java", ["get(ProductId)"], _p(ts=4))
    s.assert_artifact("art_origin", "src/catalog/OriginClient.java", _ORIGIN,
        "java", ["fetch(ProductId)"], _p(ts=5))
    s.assert_artifact("art_breaker", "src/net/CircuitBreaker.java", _BREAKER,
        "java", ["call(Supplier)"], _p(ts=6))
    s.assert_artifact("art_retry", "src/net/RetryPolicy.java", _RETRY,
        "java", ["maxAttempts()", "backoff(int)"], _p(ts=7))
    s.assert_artifact("art_productsvc", "src/catalog/ProductService.java", _PRODUCTSVC,
        "java", ["product(ProductId)"], _p(ts=8))
    s.assert_artifact("art_lb", "infra/lb.yaml", _LBCONF,
        "yaml", ["upstreams.origin"], _p(ts=9))
    s.assert_artifact("art_banner", "web/banner.html",
        "<div class=\"banner\">Spring sale!</div>\n", "html", ["banner"], _p(agent="agent_Z", ts=10))

    s.assert_node("art_incident", "artifact",
        "Incident 03-14: at 14:02 a popular product's cache entry expired during a spike; origin "
        "QPS jumped 40x for ~90s, p99 went from 120ms to 9s, checkout error rate hit 38%. The "
        "circuit breaker never opened.", _p(ts=11))

    s.assert_node("ent_singleflight", "entity",
        "Single-flight / request coalescing: concurrent misses for the same key share one "
        "in-flight origin fetch; the rest await its result instead of each calling the origin.",
        _p(ts=12))
    s.assert_node("ent_breaker_rate", "entity",
        "Error-rate circuit breaker: trips on the proportion of failures in a rolling window, so "
        "a steady high error rate opens the circuit even without a long consecutive run.", _p(ts=13))
    s.assert_node("ent_banner", "entity",
        "Banner: static homepage marketing markup.", _p(agent="agent_Z", ts=14))

    s.assert_node("dec_scale", "decision",
        "Scale out origin instances to absorb the spike.", _p(ts=15))
    s.assert_node("dec_timeout", "decision",
        "Raise the origin read timeout so slow calls succeed.", _p(ts=16))
    s.assert_node("dec_singleflight", "decision",
        "Add single-flight coalescing in CacheReadPath.get(): concurrent misses for the same id "
        "share one origin fetch; the rest wait for that result. This removes the stampede at key "
        "expiry. Supersedes scaling and timeout changes.", _p(ts=17, source="tool", conf=0.95))
    s.assert_node("dec_breaker", "decision",
        "Change CircuitBreaker to trip on error rate over a rolling window instead of consecutive "
        "failures, so a sustained error rate opens the circuit and sheds load; pair with jittered "
        "backoff to prevent synchronized retries.", _p(ts=18, source="tool", conf=0.92))
    s.assert_node("dec_banner", "decision",
        "Use the new spring-sale banner copy.", _p(agent="agent_Z", ts=19))

    s.assert_edge("task_B", "art_cacheread", "modifies", _p(ts=20))
    s.assert_edge("task_B", "dec_singleflight", "relates_to", _p(ts=21))
    s.assert_edge("task_B", "dec_breaker", "relates_to", _p(ts=22))
    s.assert_edge("task_B", "art_incident", "relates_to", _p(ts=23))
    s.assert_edge("art_cacheread", "art_origin", "depends_on", _p(ts=24))
    s.assert_edge("art_origin", "art_breaker", "depends_on", _p(ts=25))
    s.assert_edge("art_origin", "art_retry", "depends_on", _p(ts=26))
    s.assert_edge("dec_singleflight", "ent_singleflight", "derived_from", _p(ts=27))
    s.assert_edge("dec_breaker", "ent_breaker_rate", "derived_from", _p(ts=28))
    s.assert_edge("art_incident", "dec_singleflight", "relates_to", _p(ts=29))

    s.assert_edge("task_A", "dec_scale", "relates_to", _p(ts=30))
    s.assert_edge("task_A", "dec_timeout", "relates_to", _p(ts=31))
    s.supersede("dec_scale", "dec_singleflight", _p(ts=32, source="tool"))
    s.supersede("dec_timeout", "dec_singleflight", _p(ts=33, source="tool"))

    s.assert_edge("task_C", "art_banner", "modifies", _p(agent="agent_Z", ts=34))
    s.assert_edge("task_C", "dec_banner", "relates_to", _p(agent="agent_Z", ts=35))
    s.assert_edge("art_banner", "ent_banner", "derived_from", _p(agent="agent_Z", ts=36))

    return s, "task_B"


FLAT_TRANSCRIPT = f"""[AGENT A — raw session log, checkout outage RCA (03-14)]

> Task: root-cause the checkout outage. p99 exploded and the origin saturated during a spike.

Incident summary first.
$ cat incidents/2024-03-14.md
  14:02:11 a popular product's cache entry expired during a traffic spike.
  14:02:12 origin QPS jumped ~40x (from ~3k to ~120k) for about 90 seconds.
  14:02:20 origin p99 120ms -> 9s; connection pools to origin exhausted.
  14:02:25 checkout error rate 38%; users saw spinners and failed orders.
  14:03:40 recovered after the cache was manually repopulated.
  Note: the circuit breaker never opened during the whole window.

That shape — a single key expiring, then a 40x origin spike — is a classic cache stampede
(thundering herd). Let me read the read path.
$ sed -n '1,40p' src/catalog/CacheReadPath.java
{_CACHEREAD}
Confirmed: on a miss, every concurrent caller calls origin.fetch(id) independently. When the
hot key expires, thousands of in-flight requests all miss at once and each hits the origin.
There is no coalescing. That is the stampede.

Why didn't the breaker protect us? Let me look at the origin client and the breaker.
$ sed -n '1,40p' src/catalog/OriginClient.java
{_ORIGIN}
$ sed -n '1,40p' src/net/CircuitBreaker.java
{_BREAKER}
The breaker trips only after 20 CONSECUTIVE failures. Under the stampede the origin was slow
and erroring intermittently — a high error RATE, but interleaved with occasional successes, so
the consecutive counter kept resetting and the breaker never opened. A rate-based breaker would
have tripped and shed load.

And retries made it worse.
$ sed -n '1,40p' src/net/RetryPolicy.java
{_RETRY}
Up to 3 attempts with a tiny fixed backoff. During the slowdown, every request fanned out into
~3 origin calls with near-synchronized timing — a retry storm layered on top of the stampede.
No jitter, so retries synchronized.

Where does this get called from? Checkout hits it per line item.
$ sed -n '1,20p' src/catalog/ProductService.java
{_PRODUCTSVC}
$ cat infra/lb.yaml
{_LBCONF}
max_conns_per_host is 256; with the fan-out we saturated all three origins' pools almost
instantly, which is why healthy requests also failed.

Metric dump during the window:
$ ./tools/metrics.sh origin --window 14:02-14:04
  origin_qps:        p50 3100  peak 121000
  origin_inflight:   peak 41200
  origin_p99_ms:     120 -> 9100
  breaker_open_secs: 0
  retry_ratio:       2.9x
  cache_hit_ratio:   0.998 -> 0.61 (during expiry) -> 0.997

Let me reconstruct the timeline from the logs to be sure of the ordering.
$ grep -E 'origin|cache|breaker|retry' logs/catalog-*.log | sed -n '1,40p'
  14:02:11.004 cache EXPIRE key=prod:88213 (hot; ~6100 req/s reference it)
  14:02:11.006 cache MISS   key=prod:88213 inflight_misses=1
  14:02:11.007 cache MISS   key=prod:88213 inflight_misses=1180
  14:02:11.009 cache MISS   key=prod:88213 inflight_misses=5900
  14:02:11.010 origin CALL  /product/88213 (x5900 within 6ms)
  14:02:11.204 origin SLOW  /product/88213 p99=1400ms inflight=17800
  14:02:11.402 retry ATTEMPT=2 key=prod:88213 (fixed 50ms backoff, no jitter)
  14:02:11.455 retry ATTEMPT=2 key=prod:88213 (synchronized wave)
  14:02:11.610 origin SLOW  /product/88213 p99=3800ms inflight=33200
  14:02:11.702 retry ATTEMPT=3 key=prod:88213
  14:02:12.001 origin POOL_EXHAUSTED host=origin-a conns=256/256
  14:02:12.004 origin POOL_EXHAUSTED host=origin-b conns=256/256
  14:02:12.006 origin POOL_EXHAUSTED host=origin-c conns=256/256
  14:02:12.010 breaker STATE=closed consecutiveFailures=7 (reset by intermittent 200s)
  14:02:12.220 checkout ERROR downstream=origin status=timeout
  14:02:12.900 breaker STATE=closed consecutiveFailures=3 (reset again)
  14:02:20.000 origin p99=9100ms error_rate=0.41 breaker=closed
  14:03:40.000 cache REPOPULATED key=prod:88213 (manual) inflight_misses=0

The ordering confirms it: a single hot-key expiry produced ~5900 near-simultaneous misses in
6ms, each an independent origin call, then retries multiplied it, then pools exhausted across
all three origins, and the consecutive-failure breaker kept resetting on intermittent successes
so it stayed closed the whole time.

Ruling out a few other suspects so we fix the right thing:
$ sed -n '1,30p' src/net/ThreadPool.java
{_THREADPOOL}
The worker pool was near max but that is a symptom of the origin blocking, not the cause;
raising it would just let more requests pile onto the saturated origin. Not the fix.

$ sed -n '1,30p' src/net/Bulkhead.java
{_BULKHEAD}
Interesting — there is a bulkhead abstraction but the origin dependency is uncapped
(Integer.MAX_VALUE), so nothing bounded the concurrent origin calls. A bulkhead cap would help
as defense-in-depth, but the primary cause is still the stampede; coalescing is what collapses
the 40x, and a cap alone would just convert the storm into mass rejections.

$ cat ops/dashboards/origin.json
{_DASHBOARD}
The dashboard had no panel for cache_hit_ratio or inflight_misses, which is why on-call did not
see the stampede building; worth adding later, but not the code fix.

$ grep -E 'health|readiness' logs/catalog-*.log | head -5
  14:02:13 readiness OK (health check hits a static endpoint, not the origin)
Health checks stayed green because they do not exercise the origin path, so the load balancer
kept routing to saturated nodes. A deeper health check is a separate hardening item.

Connection math, to size the fix: 3 origins x 256 conns = 768 concurrent origin slots. At the
peak we had ~41k inflight origin calls wanting slots — a ~53x oversubscription. Single-flight
collapses the ~5900 misses-per-key to 1 in-flight fetch, so instead of 41k concurrent calls we
would have on the order of (number of distinct hot keys) concurrent fetches — comfortably within
768. That is the mechanism that actually fits the capacity.

Options.
Option 1: scale out origin instances to absorb spikes. Rejected — it just raises the ceiling
and costs a lot; the next hotter key or bigger spike stampedes again. It masks the bug.
Option 2: raise the origin read timeout so slow calls eventually succeed. Rejected — longer
timeouts hold connections open LONGER during a stampede, so pools exhaust faster and the storm
gets worse, not better.
Option 3 (fix): add single-flight coalescing in CacheReadPath.get() so that concurrent misses
for the same id share ONE origin fetch and the rest await its result. This collapses the 40x
spike back to ~1x per key. Pair it with a rate-based circuit breaker (trip on error rate over a
rolling window, not consecutive failures) and jittered backoff so retries desynchronize.

Root cause: no request coalescing on cache miss (stampede) plus a consecutive-failure breaker
that never trips under a steady error rate (no load shedding), amplified by un-jittered retries.
Fix: single-flight in CacheReadPath, a rate-based breaker, and jittered backoff. Scaling and
timeout changes are rejected.

(Unrelated: marketing also wants the homepage banner copy refreshed — separate task, ignore.)

Handing off. Implement single-flight coalescing in CacheReadPath.get() and switch the breaker
to an error-rate trip.
"""


def check(answer: str):
    a = answer.lower()
    crit = {
        "mechanism_singleflight": ("single-flight" in a or "single flight" in a or "coalesc" in a
                                   or "stampede" in a or "in-flight" in a or "one origin" in a
                                   or "dedupe" in a or "deduplicat" in a),
        "breaker_rate": "circuit breaker" in a or "error rate" in a or "error-rate" in a
        or "rate-based" in a or "trip" in a,
        "rejected_scale_timeout": ("scale" in a or "instance" in a or "timeout" in a)
        and ("reject" in a or "mask" in a or "not" in a or "worse" in a or "instead" in a),
    }
    misleading = (
        ("scale out" in a or "add instances" in a or "add more origin" in a
         or "increase the timeout" in a or "raise the timeout" in a)
        and ("single-flight" not in a and "coalesc" not in a and "stampede" not in a)
    )
    passed = crit["mechanism_singleflight"] and not misleading
    return passed, crit, misleading


@dataclass
class _Scenario:
    name = "outage_investigation"
    check = staticmethod(check)

    @property
    def flat_transcript(self):
        return FLAT_TRANSCRIPT

    def build(self):
        return build()


scenario = _Scenario()
