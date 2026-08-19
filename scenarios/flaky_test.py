"""flaky_test — Category 1 (coding handoff), testing/CI domain.

Agent A root-caused a flaky test to a wall-clock/timezone dependency: the code under test calls
Instant.now() directly, so the test's outcome depends on when and where it runs. The fix is to
inject a fixed Clock and advance it deterministically. Two band-aids (an @Retry annotation and a
Thread.sleep) were considered and rejected.

Correct: inject a Clock and control time in the test. Rejected: retry or sleep.
Failure mode (MISLEADING): adding a retry or sleep instead of fixing the time dependency.
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
        "Investigate the flaky test ExpiryServiceTest.testExpiryCleanup (fails ~5% of runs, more "
        "often in CI).", _p(ts=1))
    s.assert_node("task_B", "task",
        "Fix the flaky test ExpiryServiceTest.testExpiryCleanup so it passes deterministically.",
        _p(ts=2))
    s.assert_node("task_C", "task",
        "Upgrade the CI runner image to the new base.", _p(agent="agent_Z", ts=3))

    s.assert_artifact("art_service", "src/expiry/ExpiryService.java",
        "public final class ExpiryService {\n"
        "  List<Item> expired(List<Item> items) {\n"
        "    Instant now = Instant.now();   // non-deterministic: depends on wall clock\n"
        "    return items.stream().filter(i -> i.expiresAt().isBefore(now)).toList();\n"
        "  }\n"
        "}\n",
        "java", ["expired(List)"], _p(ts=4))
    s.assert_artifact("art_test", "test/ExpiryServiceTest.java",
        "class ExpiryServiceTest {\n"
        "  @Test void testExpiryCleanup() {\n"
        "    // builds items with expiresAt relative to 'now', then asserts a fixed count\n"
        "    ...\n"
        "  }\n"
        "}\n",
        "java", ["testExpiryCleanup()"], _p(ts=5))
    s.assert_artifact("art_clock", "src/util/Clock.java",
        "public interface Clock { Instant now(); }  // FixedClock available for tests\n",
        "java", ["now()"], _p(ts=6))
    s.assert_artifact("art_ci", "ci/runner.yaml",
        "image: build-base:2024.09\n", "yaml", ["image"], _p(agent="agent_Z", ts=7))

    s.assert_node("ent_clock_injection", "entity",
        "Clock injection: pass a Clock into code that needs the time so tests can supply a "
        "fixed, controllable clock instead of the wall clock.", _p(ts=8))
    s.assert_node("ent_ci_image", "entity",
        "CI base image: the container image the runners execute in.", _p(agent="agent_Z", ts=9))

    s.assert_node("dec_retry", "decision",
        "Mark the test @Retry(3) so it passes if any attempt succeeds.", _p(ts=10))
    s.assert_node("dec_sleep", "decision",
        "Add a Thread.sleep before the assertion to let timing settle.", _p(ts=11))
    s.assert_node("dec_clock", "decision",
        "Inject a Clock into ExpiryService instead of calling Instant.now() directly; the test "
        "supplies a FixedClock and controls the instant, so the outcome no longer depends on the "
        "wall clock or timezone. Root cause: ExpiryService reads Instant.now() directly. "
        "Supersedes the retry and sleep band-aids.", _p(ts=12, source="tool", conf=0.95))
    s.assert_node("dec_ci", "decision",
        "Pin the CI image to build-base:2025.01.", _p(agent="agent_Z", ts=13))

    s.assert_edge("task_B", "art_test", "modifies", _p(ts=14))
    s.assert_edge("task_B", "art_service", "modifies", _p(ts=15))
    s.assert_edge("task_B", "dec_clock", "relates_to", _p(ts=16))
    s.assert_edge("art_service", "art_clock", "depends_on", _p(ts=17))
    s.assert_edge("dec_clock", "ent_clock_injection", "derived_from", _p(ts=18))

    s.assert_edge("task_A", "dec_retry", "relates_to", _p(ts=19))
    s.assert_edge("task_A", "dec_sleep", "relates_to", _p(ts=20))
    s.supersede("dec_retry", "dec_clock", _p(ts=21, source="tool"))
    s.supersede("dec_sleep", "dec_clock", _p(ts=22, source="tool"))

    s.assert_edge("task_C", "art_ci", "modifies", _p(agent="agent_Z", ts=23))
    s.assert_edge("task_C", "dec_ci", "relates_to", _p(agent="agent_Z", ts=24))
    s.assert_edge("art_ci", "ent_ci_image", "derived_from", _p(agent="agent_Z", ts=25))

    return s, "task_B"


FLAT_TRANSCRIPT = """[AGENT A — raw session log, flaky test investigation]

> Task: ExpiryServiceTest.testExpiryCleanup fails ~5% of runs, more often in CI. Investigate.

The failures cluster near midnight and differ between local and CI. Let me look at the code.
$ sed -n '1,30p' src/expiry/ExpiryService.java
public final class ExpiryService {
  List<Item> expired(List<Item> items) {
    Instant now = Instant.now();   // non-deterministic: depends on wall clock
    return items.stream().filter(i -> i.expiresAt().isBefore(now)).toList();
  }
}
There it is: expired() calls Instant.now() directly. The test builds items with expiresAt
relative to the current time and asserts a fixed count, so whether an item is "expired" depends
on the exact wall-clock instant and the timezone of the runner. That is the flakiness.

Considered a couple of quick fixes:
- @Retry(3) on the test — rejected. It just hides the nondeterminism; the underlying code is
  still time-dependent and would bite in production reasoning.
- Thread.sleep before the assertion — rejected. Still flaky, and it slows the suite.

Real fix: inject a Clock. We already have the abstraction.
$ cat src/util/Clock.java
public interface Clock { Instant now(); }  // FixedClock available for tests
Pass a Clock into ExpiryService and call clock.now() instead of Instant.now(); in the test,
supply a FixedClock at a known instant so the expiry boundary is deterministic. Root cause is
the direct Instant.now() call; retry and sleep are rejected.

(Unrelated: someone wants to bump the CI base image — separate task; ignore.)

Handing off. Inject a Clock into ExpiryService and use a FixedClock in the test.
"""


def check(answer: str):
    a = answer.lower()
    crit = {
        "mechanism_clock": ("clock" in a or "inject" in a) and
                           ("fixed" in a or "deterministic" in a or "now()" in a or "time" in a),
        "root_cause_now": "instant.now" in a or "now()" in a or "wall clock" in a or "wall-clock" in a,
        "rejected_bandaids": ("retry" in a or "sleep" in a) and
                             ("reject" in a or "not" in a or "band" in a or "hide" in a
                              or "instead" in a),
    }
    misleading = (
        ("@retry" in a or "add a retry" in a or "thread.sleep" in a or "add a sleep" in a)
        and "clock" not in a and "inject" not in a
    )
    passed = crit["mechanism_clock"] and not misleading
    return passed, crit, misleading


@dataclass
class _Scenario:
    name = "flaky_test"
    check = staticmethod(check)

    @property
    def flat_transcript(self):
        return FLAT_TRANSCRIPT

    def build(self):
        return build()


scenario = _Scenario()
