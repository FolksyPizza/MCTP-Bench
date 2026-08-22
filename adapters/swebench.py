"""SWE-bench adapter — GitHub issue -> patch on a real repository (high context).

Loads SWE-bench records (fields: `instance_id`, `problem_statement`, `repo`, `base_commit`,
`patch`, `test_patch`, `FAIL_TO_PASS`, `PASS_TO_PASS`). The receiver is given the issue and the
repository as MCTP state (via the extractor) or as the raw file dump (transcript), and must
produce a patch. Point at the dataset with `MCTP_SWEBENCH` or `data/swebench.jsonl`; a bundled
sample with an inline repo snapshot runs offline.

Objective scoring is deferred: correct SWE-bench evaluation applies the predicted patch to a
checkout at `base_commit`, adds `test_patch`, and runs the `FAIL_TO_PASS` / `PASS_TO_PASS`
tests in the instance's environment. That harness (Docker + per-instance images) is out of band;
this adapter records the patch and the test lists, and `scoring/swebench_harness.py` is the
integration point (not yet wired). Until then these runs are judged, not objectively scored.

The repository snapshot comes from a `files` map on the record when present (the bundled sample
provides one); at scale it is materialized from a checkout of `repo@base_commit`.
"""
from __future__ import annotations

import json
import os

from .base import Adapter, Task, source_from_repo

_HERE = os.path.dirname(__file__)
_INSTRUCTION = (
    "You are resolving the GitHub issue below in the given repository. Produce a unified diff "
    "(git patch) that fixes it. Respond with only the diff inside a ```diff code block."
)


def _path() -> str:
    env = os.environ.get("MCTP_SWEBENCH")
    if env and os.path.exists(env):
        return env
    full = os.path.join(_HERE, "..", "data", "swebench.jsonl")
    return full if os.path.exists(full) else os.path.join(_HERE, "..", "data",
                                                          "swebench_sample.jsonl")


class SWEBenchAdapter(Adapter):
    name = "swebench"
    tier = "large"
    default_conditions = ("transcript", "summary", "rag", "mctp")

    def __init__(self, path: str | None = None):
        self.path = path or _path()

    def tasks(self, limit: int | None = None):
        count = 0
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                p = json.loads(line)
                tid = p["instance_id"]
                repo = p.get("files")
                if not repo:
                    # A real checkout is required; skip rather than fabricate a snapshot.
                    continue
                src = source_from_repo(self.name, tid, p["problem_statement"], repo,
                                       tier=self.tier)
                yield Task(
                    task_id=tid, source=src, receiver_instruction=_INSTRUCTION,
                    objective=None,   # deferred to the SWE-bench harness / judge
                    gold=p.get("patch", ""),
                    meta={"repo": p.get("repo"), "base_commit": p.get("base_commit"),
                          "FAIL_TO_PASS": p.get("FAIL_TO_PASS"),
                          "PASS_TO_PASS": p.get("PASS_TO_PASS"),
                          "test_patch": p.get("test_patch")},
                )
                count += 1
                if limit and count >= limit:
                    return
