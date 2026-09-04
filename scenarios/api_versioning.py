"""api_versioning — Category 2 (architecture decision transfer), API-design domain.

Agent A decided the new API version authenticates with a Bearer token in the Authorization
header; the old scheme (an access token in the URL query string) is deprecated because tokens
leak into logs, referrers, and proxies. Agent B must implement auth for the v2 endpoints and
must not reintroduce the query-string token.

Correct: validate a Bearer token from the Authorization header. Rejected: token in the query
string. Failure mode (MISLEADING): reintroducing the query-string token.
"""
from __future__ import annotations

from dataclasses import dataclass

import mctpbench  # noqa: F401
from astp import AstpStore, Provenance


def _p(agent="agent_A", ts=0, source="transcript", conf=1.0):
    return Provenance(source=source, agent=agent, model="model-x", timestamp=ts, confidence=conf)


def build():
    s = AstpStore()

    s.assert_node("task_A", "task",
        "Design authentication for the v2 API.", _p(ts=1))
    s.assert_node("task_B", "task",
        "Implement authentication for the v2 API endpoints.", _p(ts=2))
    s.assert_node("task_C", "task",
        "Add request-id logging to the gateway.", _p(agent="agent_Z", ts=3))

    s.assert_artifact("art_authfilter", "src/api/AuthFilter.java",
        "public final class AuthFilter {\n"
        "  boolean authenticate(Request r) {\n"
        "    // TODO(v2): validate the caller's credential\n"
        "    return legacyQueryTokenCheck(r);   // v1: reads ?access_token=... from the URL\n"
        "  }\n"
        "}\n",
        "java", ["authenticate(Request)", "legacyQueryTokenCheck(Request)"], _p(ts=4))
    s.assert_artifact("art_tokenverifier", "src/api/TokenVerifier.java",
        "public final class TokenVerifier {\n"
        "  boolean verifyBearer(String authorizationHeader) { ... }  // opaque token -> auth service\n"
        "}\n",
        "java", ["verifyBearer(String)"], _p(ts=5))
    s.assert_artifact("art_reqid", "src/gw/RequestId.java",
        "public final class RequestId { String next() { ... } }\n",
        "java", ["next()"], _p(agent="agent_Z", ts=6))

    s.assert_node("art_secreview", "artifact",
        "Security review note: access tokens in URLs appear in web-server logs, browser "
        "referrers, and proxy caches; they must not be used for v2.", _p(ts=7))

    s.assert_node("ent_bearer", "entity",
        "Bearer token: an opaque credential sent in the `Authorization: Bearer <token>` header "
        "and validated against the auth service per request.", _p(ts=8))
    s.assert_node("ent_querytoken", "entity",
        "Query-string token: an access token passed as a URL query parameter; deprecated.",
        _p(ts=9))
    s.assert_node("ent_reqid", "entity",
        "Request id: a per-request correlation identifier.", _p(agent="agent_Z", ts=10))

    s.assert_node("dec_querytoken", "decision",
        "Authenticate by reading an access_token query parameter from the request URL.", _p(ts=11))
    s.assert_node("dec_bearer", "decision",
        "Authenticate v2 by validating a Bearer token from the Authorization header via "
        "TokenVerifier.verifyBearer(); do not accept tokens in the URL. Reason: URL tokens leak "
        "into logs, referrers, and proxy caches. Supersedes the query-string scheme.",
        _p(ts=12, source="human", conf=0.95))
    s.assert_node("dec_reqid", "decision",
        "Generate the request id at the gateway edge.", _p(agent="agent_Z", ts=13))

    s.assert_edge("task_B", "art_authfilter", "modifies", _p(ts=14))
    s.assert_edge("task_B", "dec_bearer", "relates_to", _p(ts=15))
    s.assert_edge("task_B", "art_secreview", "relates_to", _p(ts=16))
    s.assert_edge("art_authfilter", "art_tokenverifier", "depends_on", _p(ts=17))
    s.assert_edge("dec_bearer", "ent_bearer", "derived_from", _p(ts=18))
    s.assert_edge("art_secreview", "dec_bearer", "relates_to", _p(ts=19))

    s.assert_edge("task_A", "dec_querytoken", "relates_to", _p(ts=20))
    s.supersede("dec_querytoken", "dec_bearer", _p(ts=21, source="human"))

    s.assert_edge("task_C", "art_reqid", "modifies", _p(agent="agent_Z", ts=22))
    s.assert_edge("task_C", "dec_reqid", "relates_to", _p(agent="agent_Z", ts=23))
    s.assert_edge("art_reqid", "ent_reqid", "derived_from", _p(agent="agent_Z", ts=24))

    return s, "task_B"


FLAT_TRANSCRIPT = """[AGENT A — raw session log, v2 API authentication design]

> Task: design authentication for the v2 API.

The v1 scheme reads an access token from the URL query string.
$ sed -n '1,30p' src/api/AuthFilter.java
public final class AuthFilter {
  boolean authenticate(Request r) {
    return legacyQueryTokenCheck(r);   // v1: reads ?access_token=... from the URL
  }
}
Security flagged this.
$ cat reviews/sec-221.md
  Access tokens in URLs appear in web-server logs, browser referrers, and proxy caches. This is
  a credential-leak vector and must not be used for v2.

Decision: v2 authenticates with a Bearer token in the Authorization header, validated per
request against the auth service. We already have the verifier.
$ sed -n '1,20p' src/api/TokenVerifier.java
public final class TokenVerifier {
  boolean verifyBearer(String authorizationHeader) { ... }  // opaque token -> auth service
}
So AuthFilter.authenticate() should read `Authorization: Bearer <token>` and call
TokenVerifier.verifyBearer(); it must NOT accept ?access_token= in the URL. The query-string
scheme is deprecated and rejected for v2.

(Unrelated: gateway request-id logging is a separate task; ignore.)

Handing off. Implement Bearer-header auth in AuthFilter.authenticate() for v2.
"""


def check(answer: str):
    a = answer.lower()
    crit = {
        "mechanism_bearer_header": ("bearer" in a or "authorization header" in a
                                    or "authorization: bearer" in a
                                    or ("header" in a and "token" in a)),
        "rejected_query_token": ("query" in a or "url" in a) and
                                ("reject" in a or "deprecat" in a or "not" in a or "leak" in a
                                 or "log" in a or "referrer" in a),
    }
    misleading = (
        ("query string" in a or "query parameter" in a or "?access_token" in a
         or "token in the url" in a)
        and "bearer" not in a and "authorization header" not in a
    )
    passed = crit["mechanism_bearer_header"] and not misleading
    return passed, crit, misleading


@dataclass
class _Scenario:
    name = "api_versioning"
    check = staticmethod(check)

    @property
    def flat_transcript(self):
        return FLAT_TRANSCRIPT

    def build(self):
        return build()


scenario = _Scenario()
