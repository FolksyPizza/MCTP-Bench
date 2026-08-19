# auth_migration — verbatim Agent B outputs

Runner: isolated Claude subagent, given only its context and an identical neutral question.
One trial per condition. See the MCTP experiment record for methodology.

---

## Condition FLAT (291 tok, 0 pulls) — PASS

```
1. Stateless JWT access tokens (verified per request), paired with longer-lived refresh tokens plus a refresh-token revocation list; no server-side session store.
2. Replace the per-request `legacySessionLookup` with JWT signature-and-expiry verification via `TokenService.verify()` — in `AuthMiddleware.authorize()` (AuthMiddleware.java).
3. Keep server-side sessions and scale the store (bigger cluster, read replicas) — rejected because it preserves the single point of failure and only moves the ceiling.
4. Nothing — sufficient.
```

## Condition MCTP (341 tok) — PASS, with 2 pulls

```
1. Stateless JWT access tokens (dec_jwt): signed JWTs validated per request by signature + expiry, no server-side session lookup. Paired with refresh tokens plus a revocation list (dec_refresh).
2. Replace the server-side session lookup with per-request JWT validation inside `authorize(Request)` in AuthMiddleware, delegating to `TokenService.verify(String)`; retire `legacySessionLookup(Request)`.
3. None mentioned. (The rejected status quo is the shared server-side session store, dropped as a scaling bottleneck/SPOF, but no alternative token model was weighed.)
4. Still missing: full source of AuthMiddleware and TokenService (how verify reports failure, how authorize extracts the token, whether authorize must consult the revocation list).

RETRIEVE art_authmiddleware art_tokenservice
```

Both chose JWT (no regression to sessions). Two observations: (a) the MCTP condition was
token-worse here (436 total versus 291) because the flat transcript was already concise and
the agent made two pulls; (b) because the selector excluded the superseded session decision,
the MCTP agent could not cite the rejected "scale the store" sub-alternative that the flat
agent named. See the MCTP experiment record, findings 2 and 4.
