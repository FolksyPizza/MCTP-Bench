# hidden_constraint — verbatim Agent B outputs

Runner: isolated Claude subagent, one trial per condition. See the MCTP experiment record.
This is the negative control: the required soft-delete constraint is present in the flat
transcript but not linked to the task in the graph, so the mctp packet omits it.

## Condition FLAT (300 tok, 0 pulls) — PASS
```
1. Soft-delete only: call UserService.softDelete(id) (UPDATE users SET deleted_at = now()). Do NOT use the hard-delete delete() (DELETE FROM users).
2. POST /users/bulk-delete accepting a JSON list of ids; validate size and authorization, then softDelete(id) for each in one batched transaction.
3. Must respect: hard deletes PROHIBITED (GDPR/audit); records tombstoned via deleted_at and retained until the retention window; all deletes go through the soft-delete path.
4. Nothing — sufficient.
```

## Condition MCTP (190 tok, 0 pulls) — FAIL (packet insufficient)
```
1. The file does not specify which deletion method to use — UserService exposes both delete(UserId) (hard) and softDelete(UserId), and dec_bulk only says to "delete them," so the deletion path is not stated.
2. Accept a JSON list of ids; delete in a single batched transaction; validate size and authorization. Entry point UserController.bulkDelete(List).
3. Must respect: batched write, size validation, authorization. No guidance on hard vs soft delete.
4. Missing: which method to call — delete() vs softDelete() — is ambiguous; would need the source to confirm the intended path.
```

The mctp agent correctly detected the insufficiency and abstained rather than commit to a path;
the required constraint was simply not in the packet. This confirms extraction/linking fidelity
is the ceiling, and that the suite can fail MCTP.
