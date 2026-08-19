# api_versioning — verbatim Agent B outputs

Runner: isolated Claude subagent, one trial per condition. See the MCTP experiment record.

## Condition FLAT (299 tok, 0 pulls) — PASS
```
1. Bearer token in the Authorization header (`Authorization: Bearer <token>`), validated per request; do NOT accept the v1 `?access_token=` URL scheme.
2. Change `AuthFilter.authenticate()` to read the Bearer header and call `TokenVerifier.verifyBearer()`, instead of `legacyQueryTokenCheck(r)`.
3. Rejected: the v1 query-string token scheme — access tokens in URLs leak via logs, referrers, and proxy caches (sec-221).
4. Nothing — sufficient.
```

## Condition MCTP (278 tok, 0 pulls) — PASS
```
1. Validate a Bearer token from the `Authorization: Bearer <token>` header via `TokenVerifier.verifyBearer()`; tokens in the URL are not accepted.
2. Update `authenticate(Request)` in AuthFilter to validate the Bearer token, not using `legacyQueryTokenCheck` for v2.
3. Rejected: the query-string (URL token) scheme — tokens in URLs leak into logs, referrers, and proxy caches.
4. Nothing — sufficient.
```

Both correct; the packet was sufficient with no retrieval — the smallest-overhead MCTP case.
