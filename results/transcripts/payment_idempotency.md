# payment_idempotency — verbatim Agent B outputs

Runner: isolated Claude subagent, given only its context and an identical neutral question.
One trial per condition. See the MCTP experiment record for methodology.

---

## Condition FLAT (raw transcript, 2319 tok, 0 pulls) — PASS

```
1. Server-side idempotency-key deduplication: consult the already-received Idempotency-Key before creating a charge; on a hit return the existing charge, on a miss atomically reserve the key then create.
2. In PaymentController.charge(), before charges.create(...): IdempotencyStore.find(key); if present return the existing ChargeId, else putIfAbsent(key, ...) (atomic) and only then create. Reserving the key and creating the charge must be atomic, or the key reserved first, so a crash between cannot double-charge.
3. Rejected: (a) per-user distributed lock — p99 rose to 5.2s with 61 stalled checkouts, and it does not fix cross-node retries (only serializes, never returns the first charge to the second attempt); (b) (user, amount, timestamp-window) heuristic — amount+time is not identity, causing false positives and false negatives.
4. Missing: how the key is threaded into charge(); the hit return path (id -> Charge lookup); whether putIfAbsent stores the id before/after capture (the reservation protocol).
```

## Condition MCTP (reference packet, 486 tok) — PASS, 2 pulls

```
1. Server-side idempotency-key deduplication via IdempotencyStore.putIfAbsent(key, chargeId); if a charge id already exists for the key, return the existing charge. Correct across retries and nodes.
2. In PaymentController.charge(ChargeRequest), before ChargeService.create(...): check the store for the key (find), proceed to create only if absent; recording the key and the charge must be atomic (putIfAbsent). Idempotency check strictly precedes create().
3. A lock-based approach and a heuristic approach were both considered and rejected/superseded, because idempotency-key deduplication is correct across nodes and retries. No detail on why each specifically failed.
4. Need the full source of PaymentController.charge() and IdempotencyStore — key extraction, exact signatures/return types, and how a stored ChargeId is resolved back to a response.

RETRIEVE art_controller art_idempotency
```

This is the high-context regime MCTP targets: the flat transcript is ~2,300 tokens (full file
dumps, ruled-out suspects, a benchmark), while the packet is 486 tokens and two targeted pulls
bring the total to 645 — a 72% total-token reduction at equal task success. As in
`auth_migration`, filtering the superseded decisions cost the MCTP agent the detailed rationale
for why the lock and heuristic approaches were rejected; the flat agent retained it.
