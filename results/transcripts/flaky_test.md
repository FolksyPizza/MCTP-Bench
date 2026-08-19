# flaky_test — verbatim Agent B outputs

Runner: isolated Claude subagent, one trial per condition. See the MCTP experiment record.

## Condition FLAT (386 tok, 0 pulls) — PASS
```
1. Inject a Clock into ExpiryService and call clock.now() instead of Instant.now(); the test supplies a FixedClock at a known instant.
2. Root cause: the direct Instant.now() call in ExpiryService.expired() (wall-clock/timezone dependency). Change goes in ExpiryService — take a Clock and use clock.now() in expired().
3. Rejected: @Retry(3) (hides the nondeterminism) and Thread.sleep (still flaky, slows the suite).
4. Nothing — sufficient.
```

## Condition MCTP (287 tok upfront) — PASS, 3 pulls
```
1. Inject a Clock into ExpiryService (test supplies a FixedClock), instead of Instant.now().
2. Root cause: ExpiryService reads Instant.now() directly; read time via the injected Clock in expired(List).
3. Rejected: retry and sleep band-aids — superseded by Clock injection; they don't remove the wall-clock/timezone dependency.
4. Would retrieve [art_service], [art_clock], [art_test] to place the injection and wire the FixedClock.
```

Both correct; the mctp agent got the fix from the packet and requested the source files to place it.
