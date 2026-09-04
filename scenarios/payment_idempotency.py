"""payment_idempotency — Category 4 (larger repository task, high token count).

A long incident investigation into duplicate charges under retries. The flat transcript is
several thousand tokens: it inlines the full source of several files, log excerpts, a
benchmark, and reasoning across three approaches (two rejected, one superseded). The ASTP
packet carries the two live decisions plus references to the three relevant files.

Correct fix: idempotency keys — the charge path must check an idempotency store / ledger for
the request's key before charging, and record the key atomically. Root cause: retries create a
new charge because the charge path never dedupes by idempotency key.

Rejected/superseded approaches (present in the flat transcript, filtered from the packet):
a per-user distributed lock (contention, and it does not survive cross-node retries) and a
(user, amount, timestamp) heuristic (false positives and negatives).

This scenario exists to test the regime where ASTP is expected to help: a large, noisy context
where most content is prunable.
"""
from __future__ import annotations

from dataclasses import dataclass

import mctpbench  # noqa: F401
from astp import AstpStore, Provenance


def _p(agent="agent_A", ts=0, source="transcript", conf=1.0):
    return Provenance(source=source, agent=agent, model="model-x", timestamp=ts, confidence=conf)


_PAYMENTCONTROLLER = """public final class PaymentController {
  private final ChargeService charges;
  // POST /charge — entry point for a payment request.
  Response charge(ChargeRequest req) {
    // BUG: no idempotency check; a retried request creates a second charge.
    Charge c = charges.create(req.userId(), req.amountCents(), req.currency());
    return Response.ok(c.id());
  }
}
"""

_CHARGESERVICE = """public final class ChargeService {
  private final Gateway gateway;
  private final Ledger ledger;
  Charge create(UserId user, long amountCents, String currency) {
    Charge c = gateway.authorizeAndCapture(user, amountCents, currency);
    ledger.record(c);            // appends to the immutable ledger
    return c;
  }
}
"""

_IDEMPOTENCYSTORE = """public final class IdempotencyStore {
  // Persistent map: idempotencyKey -> chargeId. Shared across nodes.
  Optional<ChargeId> find(String key) { ... }
  // Atomic put-if-absent; returns the existing charge id on a duplicate key.
  Optional<ChargeId> putIfAbsent(String key, ChargeId id) { ... }
}
"""

_LEDGER = """public final class Ledger {
  void record(Charge c) { ... }              // append-only
  List<Charge> forUser(UserId u, Instant since) { ... }
}
"""

_RETRYPOLICY = """public final class RetryPolicy {
  // Client and gateway both retry on timeout; retries reuse the same Idempotency-Key header.
  int maxAttempts() { return 3; }
  Duration backoff(int attempt) { ... }
}
"""


def build():
    s = AstpStore()

    s.assert_node("task_A", "task",
        "Investigate duplicate charges: some users are charged two or three times for a single "
        "checkout during traffic spikes.", _p(ts=1))
    s.assert_node("task_B", "task",
        "Fix duplicate charges in the payment path so retried requests do not create extra "
        "charges.", _p(ts=2))
    s.assert_node("task_C", "task",
        "Localize transactional email templates for the payments service.", _p(agent="agent_Z", ts=3))

    # relevant code
    s.assert_artifact("art_controller", "src/pay/PaymentController.java", _PAYMENTCONTROLLER,
        "java", ["charge(ChargeRequest)"], _p(ts=4))
    s.assert_artifact("art_chargeservice", "src/pay/ChargeService.java", _CHARGESERVICE,
        "java", ["create(UserId, long, String)"], _p(ts=5))
    s.assert_artifact("art_idempotency", "src/pay/IdempotencyStore.java", _IDEMPOTENCYSTORE,
        "java", ["find(String)", "putIfAbsent(String, ChargeId)"], _p(ts=6))
    # present but secondary
    s.assert_artifact("art_ledger", "src/pay/Ledger.java", _LEDGER,
        "java", ["record(Charge)", "forUser(UserId, Instant)"], _p(ts=7))
    s.assert_artifact("art_retry", "src/pay/RetryPolicy.java", _RETRYPOLICY,
        "java", ["maxAttempts()", "backoff(int)"], _p(ts=8))
    # irrelevant subsystem
    s.assert_artifact("art_email", "src/mail/EmailRenderer.java",
        "public final class EmailRenderer { String render(Template t, Model m) { ... } }\n",
        "java", ["render(Template, Model)"], _p(agent="agent_Z", ts=9))

    s.assert_node("art_incident", "artifact",
        "Incident #712: during spikes, ~0.3% of checkouts produce 2-3 charges. Correlates with "
        "gateway timeouts and client retries. Idempotency-Key header is present on every retry "
        "but is not consulted server-side.", _p(ts=10))

    # entities
    s.assert_node("ent_idempotency", "entity",
        "Idempotency key: a client-supplied key identifying a single logical operation; the "
        "server must make repeated requests with the same key have the effect of one.", _p(ts=11))
    s.assert_node("ent_ledger", "entity",
        "Ledger: append-only record of charges; source of truth for what was charged.", _p(ts=12))
    s.assert_node("ent_email", "entity",
        "Template localization: per-locale message catalogs.", _p(agent="agent_Z", ts=13))

    # decisions
    s.assert_node("dec_lock", "decision",
        "Serialize charges with a per-user distributed lock during checkout.", _p(ts=14))
    s.assert_node("dec_heuristic", "decision",
        "Deduplicate charges by a (user, amount, timestamp-window) heuristic.", _p(ts=15))
    s.assert_node("dec_idempotency", "decision",
        "Deduplicate by idempotency key: on charge, IdempotencyStore.putIfAbsent(key, ...) "
        "atomically; if a charge id already exists for the key, return it instead of charging "
        "again. Reason: the Idempotency-Key header is already sent on every retry, and this is "
        "correct across nodes and retries. Supersedes the lock and heuristic approaches.",
        _p(ts=16, source="tool", conf=0.95))
    s.assert_node("dec_check_order", "decision",
        "The idempotency check must happen in PaymentController.charge() before ChargeService."
        "create(); recording the key and the charge must be atomic so a crash between them "
        "cannot double-charge.", _p(ts=17, source="tool", conf=0.9))
    s.assert_node("dec_email", "decision",
        "Store locale catalogs as flat JSON keyed by message id.", _p(agent="agent_Z", ts=18))

    # relations (relevant cluster)
    s.assert_edge("task_B", "art_controller", "modifies", _p(ts=19))
    s.assert_edge("task_B", "dec_idempotency", "relates_to", _p(ts=20))
    s.assert_edge("task_B", "dec_check_order", "relates_to", _p(ts=21))
    s.assert_edge("task_B", "art_incident", "relates_to", _p(ts=22))
    s.assert_edge("art_controller", "art_chargeservice", "calls", _p(ts=23))
    s.assert_edge("art_controller", "art_idempotency", "depends_on", _p(ts=24))
    s.assert_edge("art_chargeservice", "art_ledger", "depends_on", _p(ts=25))
    s.assert_edge("art_idempotency", "ent_idempotency", "derived_from", _p(ts=26))
    s.assert_edge("art_ledger", "ent_ledger", "derived_from", _p(ts=27))
    s.assert_edge("art_incident", "dec_check_order", "relates_to", _p(ts=28))

    # rejected/superseded approaches
    s.assert_edge("task_A", "dec_lock", "relates_to", _p(ts=29))
    s.assert_edge("task_A", "dec_heuristic", "relates_to", _p(ts=30))
    s.supersede("dec_lock", "dec_idempotency", _p(ts=31, source="tool"))
    s.supersede("dec_heuristic", "dec_idempotency", _p(ts=32, source="tool"))

    # irrelevant subsystem
    s.assert_edge("task_C", "art_email", "modifies", _p(agent="agent_Z", ts=33))
    s.assert_edge("task_C", "dec_email", "relates_to", _p(agent="agent_Z", ts=34))
    s.assert_edge("art_email", "ent_email", "derived_from", _p(agent="agent_Z", ts=35))

    return s, "task_B"


FLAT_TRANSCRIPT = f"""[AGENT A — raw session log, duplicate-charge investigation (incident #712)]

> Task: some users are charged 2-3 times for one checkout during traffic spikes. Investigate.

$ cat incidents/712.md
  During spikes, ~0.3% of checkouts produce 2-3 charges. Correlates with gateway timeouts and
  client retries. The Idempotency-Key header is present on every retry but is not consulted
  server-side. Refunds are piling up; this is customer-facing.

Let me trace the charge path. Start at the controller.
$ sed -n '1,40p' src/pay/PaymentController.java
{_PAYMENTCONTROLLER}
So the controller calls ChargeService.create() directly. No idempotency check at all. Let me
look at the service.
$ sed -n '1,40p' src/pay/ChargeService.java
{_CHARGESERVICE}
create() authorizes-and-captures on the gateway, then records to the ledger. Nothing dedupes.
So if the client retries after a gateway timeout (the capture may actually have succeeded but
the response was lost), we authorize-and-capture AGAIN. That's the double charge.

Before assuming it is the charge path, let me rule out a few other suspects — this incident
touched a lot of code and I want to be sure.

Suspect: duplicate webhooks from the gateway re-notifying us.
$ sed -n '1,45p' src/pay/WebhookHandler.java
public final class WebhookHandler {{
  private final Ledger ledger;
  // Gateway posts charge.succeeded events here; delivery is at-least-once.
  void onEvent(WebhookEvent e) {{
    if (e.type() == CHARGE_SUCCEEDED) {{
      ledger.annotate(e.chargeId(), e.payload());   // idempotent annotate; never a new charge
    }}
  }}
}}
Dead end: onEvent only annotates an existing charge, it never creates one. Webhooks are not the
source of the duplicates. Ruling out.

Suspect: the payment gateway client double-submitting internally.
$ sed -n '1,50p' src/pay/Gateway.java
public final class Gateway {{
  private final HttpClient http;
  Charge authorizeAndCapture(UserId user, long amountCents, String currency) {{
    // Single POST to the processor; on timeout it throws GatewayTimeout (no internal retry).
    HttpResponse r = http.post("/v1/capture", body(user, amountCents, currency));
    if (r.timedOut()) throw new GatewayTimeout();
    return parseCharge(r);
  }}
}}
So the Gateway does not retry internally — a GatewayTimeout propagates up and it is the
RetryPolicy / client that retries. The double captures are real captures from separate
attempts, not a gateway-internal resend. Ruling out gateway double-submit.

Suspect: a bad deploy or config. Checked the service config.
$ cat config/pay.yaml
  gateway:
    endpoint: https://proc.example/v1
    timeoutMs: 3500
  retry:
    maxAttempts: 3
    backoffMs: [100, 400, 1600]
  idempotency:
    enabled: false      # a flag exists, but it is off and not read anywhere in the code
There is an idempotency.enabled flag in config that is false and unused — someone scaffolded
idempotency configuration but never wired the check. That lines up with what I am seeing.

Broader log context across affected orders:
$ grep -E 'attempt=(2|3).*OK' logs/pay-*.log | wc -l
  188
$ grep -E 'attempt=(2|3).*OK' logs/pay-*.log | head -8
  12:01:06.204 gateway OK charge=ch_aa11 user=u_44197 key=idem_7f3a attempt=2
  12:01:06.501 gateway OK charge=ch_bb22 user=u_44197 key=idem_7f3a attempt=3
  12:03:44.010 gateway OK charge=ch_cd31 user=u_5521  key=idem_1b0c attempt=2
  12:03:44.290 gateway OK charge=ch_cd90 user=u_5521  key=idem_1b0c attempt=3
  12:09:11.755 gateway OK charge=ch_ef02 user=u_88213 key=idem_44de attempt=2
  12:11:02.113 gateway OK charge=ch_ef77 user=u_88213 key=idem_44de attempt=2
  12:15:20.900 gateway OK charge=ch_1200 user=u_3390  key=idem_9a1f attempt=2
  12:15:21.010 gateway OK charge=ch_1201 user=u_3390  key=idem_9a1f attempt=3
188 second/third attempts captured, every one reusing the same key the first attempt used. The
server has the key on every one of these and does nothing with it.

Let me confirm the retry behavior.
$ sed -n '1,40p' src/pay/RetryPolicy.java
{_RETRYPOLICY}
Right — up to 3 attempts, and crucially the retries REUSE the same Idempotency-Key header. So
the client is already giving us everything we need to dedupe; the server just ignores it.

Let me check the logs around a known double charge (user u_44197, order o_9981).
$ grep 'o_9981' logs/pay-*.log | head -20
  12:01:02.114 charge start   user=u_44197 amount=4999 key=idem_7f3a attempt=1
  12:01:05.882 gateway TIMEOUT user=u_44197 attempt=1
  12:01:05.913 charge start   user=u_44197 amount=4999 key=idem_7f3a attempt=2
  12:01:06.204 gateway OK      charge=ch_aa11 user=u_44197 attempt=2
  12:01:06.219 charge start   user=u_44197 amount=4999 key=idem_7f3a attempt=3
  12:01:06.501 gateway OK      charge=ch_bb22 user=u_44197 attempt=3
  -> two successful captures (ch_aa11, ch_bb22) for the same key idem_7f3a. Confirmed.

Now, options. Let me think through three.

Option 1: a per-user distributed lock around checkout, so only one charge for a user runs at a
time. I sketched it and benchmarked lock contention under load.
$ ./bench/run.sh lock_contention
  {{
    "per_user_lock": {{ "p50_ms": 90, "p99_ms": 5200, "stalled_checkouts": 61 }},
    "no_lock":       {{ "p50_ms": 24, "p99_ms": 130,  "stalled_checkouts": 0 }}
  }}
Two problems: (a) contention is bad — p99 jumps to 5.2s and 61 checkouts stalled; (b) more
fundamentally, a lock does NOT fix cross-node retries: attempt=2 and attempt=3 can land on
different app nodes, and a per-user lock in one node's memory won't see the other. Even a
distributed lock only serializes; it doesn't make the second attempt return the first charge.
Rejecting the lock approach.

Option 2: dedupe by a (user, amount, timestamp-window) heuristic — if we saw the same user and
amount within N seconds, treat it as a duplicate. Problem: false positives (a user legitimately
buying the same item twice in a minute is dropped) and false negatives (a slow retry outside the
window still double-charges). Amount+time is not identity. Rejecting the heuristic.

Option 3: use the idempotency key we already receive. On charge, look the key up in a shared
IdempotencyStore; if a charge already exists for that key, return it; otherwise reserve the key
atomically (put-if-absent) and proceed. This is correct across nodes and across retries, and it
needs no new client contract because the Idempotency-Key header is already sent.
$ sed -n '1,40p' src/pay/IdempotencyStore.java
{_IDEMPOTENCYSTORE}
putIfAbsent is exactly the atomic primitive we need. And the Ledger stays the source of truth:
$ sed -n '1,40p' src/pay/Ledger.java
{_LEDGER}
Root cause + fix: PaymentController.charge() must, before calling ChargeService.create(),
consult IdempotencyStore for req's key; on a hit, return the existing charge; on a miss,
putIfAbsent(key, ...) atomically and only then create. The reservation of the key and the
creation of the charge must be atomic (or the key reserved first) so a crash in between cannot
double-charge. Idempotency is the fix; the lock and the heuristic are rejected.

(Unrelated: while paging through the repo I also noticed the email templates aren't localized —
EmailRenderer has no locale handling. Separate task; ignore for #712.)

Handing off. Someone implement the idempotency check in PaymentController.charge().
"""


def check(answer: str):
    a = answer.lower()
    crit = {
        "mechanism_idempotency": "idempoten" in a,
        "check_before_charge": ("before" in a or "putifabsent" in a or "put-if-absent" in a
                                or "reserve" in a) and ("charge" in a or "create" in a or "key" in a),
        "rejected_alternatives": ("lock" in a or "heuristic" in a or "timestamp" in a)
        and ("reject" in a or "instead" in a or "contention" in a or "not" in a or "cross-node" in a
             or "false" in a),
    }
    # MISLEADING: proposes a distributed lock as the fix, without idempotency.
    misleading = (
        any(p in a for p in ("distributed lock", "per-user lock", "add a lock", "use a lock"))
        and "idempoten" not in a
    )
    passed = crit["mechanism_idempotency"] and not misleading
    return passed, crit, misleading


@dataclass
class _Scenario:
    name = "payment_idempotency"
    check = staticmethod(check)

    @property
    def flat_transcript(self):
        return FLAT_TRANSCRIPT

    def build(self):
        return build()


scenario = _Scenario()
