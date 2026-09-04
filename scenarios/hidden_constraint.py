"""hidden_constraint — a case where ASTP is expected to underperform.

A critical constraint (all user-record deletions must go through the soft-delete tombstone path;
hard DELETE is forbidden for GDPR/audit) is present in the flat transcript, but in the ASTP
graph it was recorded against the compliance-review task and never linked to the new
bulk-delete task. This models an extraction/linking miss: the fact exists in the graph but is
not reachable from the task, so the selector's packet omits it.

Expected outcome: the flat condition sees the constraint and answers with soft-delete; the mctp
condition, missing it, proposes a plain (hard) bulk delete or has to flag that it lacks the
deletion policy. This demonstrates that extraction fidelity is the system's ceiling and that
the benchmark can fail ASTP.

Correct answer: bulk-delete via the soft-delete / tombstone path.
"""
from __future__ import annotations

from dataclasses import dataclass

import mctpbench  # noqa: F401
from astp import AstpStore, Provenance


def _p(agent="agent_A", ts=0, source="transcript", conf=1.0):
    return Provenance(source=source, agent=agent, model="model-x", timestamp=ts, confidence=conf)


def build():
    s = AstpStore()

    # The constraint is attached to the compliance-review task, not the new endpoint task.
    s.assert_node("task_A", "task",
        "Review data-deletion compliance for user records.", _p(ts=1))
    s.assert_node("task_B", "task",
        "Add a bulk-delete endpoint that removes user records for a list of user ids.", _p(ts=2))
    s.assert_node("task_C", "task",
        "Add pagination to the user-search endpoint.", _p(agent="agent_Z", ts=3))

    s.assert_artifact("art_userservice", "src/users/UserService.java",
        "public final class UserService {\n"
        "  void delete(UserId id) { db.exec(\"DELETE FROM users WHERE id = ?\", id); }  // hard\n"
        "  void softDelete(UserId id) { db.exec(\"UPDATE users SET deleted_at = now() WHERE id = ?\", id); }\n"
        "}\n",
        "java", ["delete(UserId)", "softDelete(UserId)"], _p(ts=4))
    s.assert_artifact("art_controller", "src/users/UserController.java",
        "public final class UserController {\n"
        "  // TODO: add POST /users/bulk-delete accepting a list of ids\n"
        "}\n",
        "java", ["bulkDelete(List)"], _p(ts=5))
    s.assert_artifact("art_search", "src/users/UserSearch.java",
        "public final class UserSearch { List<User> search(Query q) { ... } }\n",
        "java", ["search(Query)"], _p(agent="agent_Z", ts=6))

    # The critical constraint — recorded, but linked to the compliance task, not task_B.
    s.assert_node("dec_softdelete", "decision",
        "All user-record deletions must go through the soft-delete tombstone path "
        "(UserService.softDelete: set deleted_at, retain for the audit/retention window). A hard "
        "DELETE is forbidden for GDPR and audit reasons.", _p(ts=7, source="human", conf=0.98))
    s.assert_node("art_policy", "artifact",
        "Data-retention policy: user records are tombstoned on deletion (deleted_at set) and "
        "physically retained until the retention window elapses; hard deletes are prohibited.",
        _p(ts=8))
    s.assert_node("ent_tombstone", "entity",
        "Tombstone: a soft-delete marker (deleted_at) that hides a record while retaining it.",
        _p(ts=9))

    # A generic implementation decision that is linked to task_B and says nothing about soft-delete.
    s.assert_node("dec_bulk", "decision",
        "Accept a JSON list of user ids and delete them in one batched transaction; validate the "
        "list size and authorization.", _p(ts=10, source="tool", conf=0.9))
    s.assert_node("ent_batch", "entity",
        "Batched write: apply many row operations in a single transaction.", _p(ts=11))

    # task_B cluster — note: NOT connected to dec_softdelete / art_policy.
    s.assert_edge("task_B", "art_controller", "modifies", _p(ts=12))
    s.assert_edge("task_B", "art_userservice", "depends_on", _p(ts=13))
    s.assert_edge("task_B", "dec_bulk", "relates_to", _p(ts=14))
    s.assert_edge("dec_bulk", "ent_batch", "derived_from", _p(ts=15))

    # compliance cluster — where the constraint actually lives (unreachable from task_B).
    s.assert_edge("task_A", "dec_softdelete", "relates_to", _p(ts=16))
    s.assert_edge("task_A", "art_policy", "relates_to", _p(ts=17))
    s.assert_edge("dec_softdelete", "ent_tombstone", "derived_from", _p(ts=18))

    # unrelated
    s.assert_edge("task_C", "art_search", "modifies", _p(agent="agent_Z", ts=19))

    return s, "task_B"


FLAT_TRANSCRIPT = """[AGENT A — raw session log, bulk-delete endpoint]

> Task: add a bulk-delete endpoint that removes user records for a list of user ids.

First, the deletion policy — I checked compliance before touching deletes.
$ cat policies/data-retention.md
  User records are tombstoned on deletion (deleted_at set) and physically retained until the
  retention window elapses. Hard deletes are PROHIBITED for GDPR and audit reasons. All deletes
  must go through the soft-delete path.

So whatever the endpoint does, it must soft-delete, not hard-delete. Let me look at the service.
$ sed -n '1,20p' src/users/UserService.java
public final class UserService {
  void delete(UserId id) { db.exec("DELETE FROM users WHERE id = ?", id); }  // hard — do NOT use
  void softDelete(UserId id) { db.exec("UPDATE users SET deleted_at = now() WHERE id = ?", id); }
}
There are two methods; delete() is a hard DELETE and must not be used for user records.
softDelete() sets deleted_at — that's the compliant path.

Plan: add POST /users/bulk-delete in UserController that accepts a JSON list of ids, validates
size and authorization, and calls UserService.softDelete(id) for each in one batched
transaction. It must NOT call delete().

Handing off. Implement bulk-delete using the soft-delete path only.
"""


def check(answer: str):
    a = answer.lower()
    crit = {
        "respects_soft_delete": ("soft" in a or "tombstone" in a or "deleted_at" in a)
        and "delete" in a,
        "mechanism_bulk": "bulk" in a or "batch" in a or "list" in a,
    }
    # MISLEADING: proposes a hard/permanent delete with no mention of the soft-delete path.
    misleading = (
        ("hard delete" in a or "permanently" in a or "physically" in a or "delete from users" in a
         or "userservice.delete" in a)
        and "soft" not in a and "tombstone" not in a and "deleted_at" not in a
    )
    passed = crit["respects_soft_delete"] and not misleading
    return passed, crit, misleading


@dataclass
class _Scenario:
    name = "hidden_constraint"
    check = staticmethod(check)

    @property
    def flat_transcript(self):
        return FLAT_TRANSCRIPT

    def build(self):
        return build()


scenario = _Scenario()
