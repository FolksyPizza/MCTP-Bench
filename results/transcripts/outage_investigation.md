# outage_investigation — verbatim Agent B outputs

Runner: isolated Claude subagent, one trial per condition. See the MCTP experiment record.
This is the largest scenario (~2,500-token flat transcript).

## Condition FLAT (2476 tok, 0 pulls) — PASS
```
1. Add single-flight coalescing in CacheReadPath.get() so concurrent misses for the same id share ONE origin fetch (collapsing the ~40x spike to ~1x/key, within the 768 origin connection slots); pair with a rate-based circuit breaker and jittered backoff.
2. Root cause: no request coalescing on cache miss (stampede), a consecutive-failure CircuitBreaker that never trips under a steady error rate, amplified by un-jittered retries. Primary change in CacheReadPath.get(); secondary in CircuitBreaker.call() (rate-based) and RetryPolicy.backoff() (jitter).
3. Rejected: scale out origin instances (masks the bug, next spike stampedes again); raise the read timeout (holds connections longer, exhausts pools faster). Set aside: raising the ThreadPool (symptom); a Bulkhead cap (defense-in-depth only); dashboard/health-check gaps (hardening, not the fix).
4. Nothing — sufficient.
```

## Condition MCTP (503 tok upfront) — PASS, 4 pulls
```
1. Single-flight / request coalescing so concurrent misses for the same id share one in-flight origin fetch, plus a rate-based circuit breaker (rolling window) with jittered backoff.
2. Root cause: hot-key expiry -> cache stampede + retry storm, breaker never opened. Primary change in CacheReadPath.get(ProductId); breaker change in CircuitBreaker.call(Supplier); jitter in RetryPolicy.
3. Scale and timeout changes were considered but superseded/rejected in favor of single-flight [dec_singleflight]; consecutive-failure tripping replaced by error-rate tripping.
4. Would retrieve art_cacheread, art_breaker, art_retry, art_origin for current signatures and how backoff/breaker are wired.
```

Both correct. The flat baseline additionally retained the ruled-out dead-ends (thread pool,
bulkhead, health checks); the mctp packet dropped them and the receiver requested the four
files it needed. Total tokens fell 67% at equal correctness.
