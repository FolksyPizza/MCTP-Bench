# artifact_selection — verbatim Agent B outputs

Runner: isolated Claude subagent, given only its context and an identical neutral question.
One trial per condition. See the MCTP experiment record for methodology.

---

## Condition FLAT (all config files inline, 184 tok, 0 pulls) — PASS

```
1. 20
2. config/payments/db.yaml
```

Not misled by the look-alike cache pool value (50) present in the same dump.

## Condition MCTP (single reference, 103 tok) — PASS, 1 targeted pull

Round 1 (from the reference alone):
```
1. Unknown from the provided context — the pool size value is not included in the handoff (only the symbol path `database.pool.size` is asserted, not its value).
2. config/payments/db.yaml

RETRIEVE art_dbconfig
```

Round 2 (after the 34-token retrieve was fulfilled):
```
1. 20 (max DB connections)
2. config/payments/db.yaml
```

The MCTP condition delivered only the relevant reference; the agent identified the correct
file, recognized the value required retrieval, and pulled exactly one artifact. The look-alike
cache pool value was never delivered, so the failure surface that existed in the flat
condition did not exist here.
