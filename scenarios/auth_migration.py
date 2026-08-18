"""auth_migration — Category 2 (architecture decision transfer).

Agent A migrated authentication from server-side sessions to stateless JWT access tokens
after the shared session store became a scaling bottleneck, and added refresh tokens with a
revocation list to preserve logout/revocation. The session-store approach is superseded.
Agent B must continue the migration without regressing to server-side sessions.

Success: adopts JWT; identifies the rejected session-store approach and why; does not propose
sessions as the solution.
Failure mode (MISLEADING): recommends keeping server-side sessions.
Why MCTP helps: the superseded decision is excluded from the packet via the supersedes edge,
and the current decision carries its rationale.
"""
from __future__ import annotations

from dataclasses import dataclass

import mctpbench  # noqa: F401
from mctp import MCTPStore, Provenance


def _p(agent="agent_A", ts=0, source="transcript", conf=1.0):
    return Provenance(source=source, agent=agent, model="model-x", timestamp=ts, confidence=conf)


def build():
    s = MCTPStore()

    s.assert_node("task_A", "task",
        "Investigate authentication latency and failures under load; the shared session store "
        "is a suspected bottleneck.", _p(ts=1))
    s.assert_node("task_B", "task",
        "Continue the authentication migration: implement per-request auth validation for the "
        "chosen token model.", _p(ts=2))
    s.assert_node("task_C", "task",
        "Improve transactional email template rendering.", _p(agent="agent_Z", ts=3))

    s.assert_artifact("art_authmiddleware", "src/auth/AuthMiddleware.java",
        "public final class AuthMiddleware {\n"
        "  private final TokenService tokens;\n"
        "  boolean authorize(Request r) {\n"
        "    // TODO: validate the request's credential per the chosen model\n"
        "    return legacySessionLookup(r);   // still hitting the session store\n"
        "  }\n"
        "}\n",
        "java", ["authorize(Request)", "legacySessionLookup(Request)"], _p(ts=4))
    s.assert_artifact("art_tokenservice", "src/auth/TokenService.java",
        "public final class TokenService {\n"
        "  String issue(UserId u) { ... }\n"
        "  boolean verify(String jwt) { ... }   // signature + expiry\n"
        "  void revokeRefresh(String refreshId) { ... }\n"
        "}\n",
        "java", ["issue(UserId)", "verify(String)", "revokeRefresh(String)"], _p(ts=5))
    s.assert_artifact("art_email", "src/mail/EmailRenderer.java",
        "public final class EmailRenderer { String render(Template t, Model m) { ... } }\n",
        "java", ["render(Template, Model)"], _p(agent="agent_Z", ts=6))

    s.assert_node("art_incident", "artifact",
        "Incident: login p99 spiked and the session store approached connection limits during "
        "traffic peaks; failures correlated with session-store saturation.", _p(ts=7))

    s.assert_node("ent_jwt", "entity",
        "Stateless access token: a signed JWT validated per request by signature and expiry, "
        "with no server-side session lookup.", _p(ts=8))
    s.assert_node("ent_refresh", "entity",
        "Refresh + revocation: short-lived access tokens paired with longer-lived refresh "
        "tokens; a revocation list supports logout and forced revocation.", _p(ts=9))
    s.assert_node("ent_templating", "entity",
        "Template rendering: precompiled templates with a model binding step.", _p(agent="agent_Z", ts=10))

    s.assert_node("dec_sessions", "decision",
        "Keep server-side sessions in a shared session store.", _p(ts=11))
    s.assert_node("dec_jwt", "decision",
        "Migrate to stateless JWT access tokens validated per request (signature + expiry), "
        "removing the server-side session lookup. Reason: the shared session store was a "
        "scaling bottleneck and single point of failure under load.", _p(ts=12, source="tool", conf=0.9))
    s.assert_node("dec_refresh", "decision",
        "Pair short-lived access tokens with longer-lived refresh tokens and maintain a "
        "refresh-token revocation list, so logout and revocation still work without sessions.",
        _p(ts=13, source="tool", conf=0.92))
    s.assert_node("dec_email", "decision",
        "Precompile email templates at startup to cut render latency.", _p(agent="agent_Z", ts=14))

    s.assert_edge("task_B", "art_authmiddleware", "modifies", _p(ts=15))
    s.assert_edge("task_B", "dec_jwt", "relates_to", _p(ts=16))
    s.assert_edge("task_B", "dec_refresh", "relates_to", _p(ts=17))
    s.assert_edge("task_B", "art_incident", "relates_to", _p(ts=18))
    s.assert_edge("art_authmiddleware", "art_tokenservice", "depends_on", _p(ts=19))
    s.assert_edge("art_tokenservice", "ent_jwt", "derived_from", _p(ts=20))
    s.assert_edge("art_tokenservice", "ent_refresh", "derived_from", _p(ts=21))
    s.assert_edge("art_incident", "dec_jwt", "relates_to", _p(ts=22))

    s.assert_edge("task_A", "dec_sessions", "relates_to", _p(ts=23))
    s.supersede("dec_sessions", "dec_jwt", _p(ts=24, source="tool"))

    s.assert_edge("task_C", "art_email", "modifies", _p(agent="agent_Z", ts=25))
    s.assert_edge("task_C", "dec_email", "relates_to", _p(agent="agent_Z", ts=26))
    s.assert_edge("art_email", "ent_templating", "derived_from", _p(agent="agent_Z", ts=27))

    return s, "task_B"


FLAT_TRANSCRIPT = """[AGENT A — raw session log, authentication scaling investigation]

> Task: auth latency and failures under load; suspect the session store.

$ cat incidents/auth-latency.md
  Login p99 spiked during peaks; the shared session store approached its connection limit;
  failures correlated with session-store saturation.

Current design keeps server-side sessions in a shared store, and AuthMiddleware.authorize()
does a legacySessionLookup on every request. Under load that store is the bottleneck and a
single point of failure.

First option considered: keep server-side sessions and scale the store (bigger cluster,
read replicas). Rejected — it keeps the single point of failure and just moves the ceiling;
the coupling to a stateful store is the real problem.

Chosen approach: migrate to stateless JWT access tokens. AuthMiddleware validates each
request by verifying the JWT signature and expiry via TokenService.verify(), with no session
lookup. Concern with JWT is revocation, so: pair short-lived access tokens with longer-lived
refresh tokens and keep a refresh-token revocation list; logout and forced revocation go
through TokenService.revokeRefresh().

Files: AuthMiddleware.java (authorize path, currently legacySessionLookup), TokenService.java
(issue/verify/revokeRefresh).

(Unrelated: also noted email render latency — precompiling templates helps. Ignore for auth.)

Handing off. Implement per-request JWT validation in AuthMiddleware.authorize().
"""


def check(answer: str):
    a = answer.lower()
    crit = {
        "mechanism_jwt": "jwt" in a and ("stateless" in a or "signature" in a or "per request" in a
                                         or "per-request" in a or "verify" in a),
        "revocation_refresh": "refresh" in a and ("revocation" in a or "revoke" in a or "logout" in a),
        "rejected_sessions": "session" in a and ("reject" in a or "instead" in a or "bottleneck" in a
                                                 or "single point" in a or "remov" in a or "no session" in a),
    }
    misleading = (
        any(p in a for p in ("keep server-side session", "use server-side session",
                             "keep the session store", "scale the session store",
                             "stay with sessions"))
        and "jwt" not in a
    )
    passed = crit["mechanism_jwt"] and not misleading
    return passed, crit, misleading


@dataclass
class _Scenario:
    name = "auth_migration"
    check = staticmethod(check)

    @property
    def flat_transcript(self):
        return FLAT_TRANSCRIPT

    def build(self):
        return build()


scenario = _Scenario()
