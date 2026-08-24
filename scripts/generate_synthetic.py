#!/usr/bin/env python3
"""Generate the synthetic in-house suites (multifile, swarm) at scale.

These suites have no external dataset — the tasks are constructed here from parametric templates
with known ground truth. This is SYNTHETIC data by construction, and is labelled as such: every
generated task carries `"synthetic": true`, and any model later trained on these episodes is
trained on synthetic data (see docs and the model card). Generation is seedless-deterministic
(varied by index, not RNG) so the set is reproducible.

    python scripts/generate_synthetic.py --suite multifile --n 300
    python scripts/generate_synthetic.py --suite swarm --n 40

Writes data/multifile.jsonl and data/swarm.jsonl. The adapters prefer these files when present,
falling back to the small bundled samples otherwise.
"""
from __future__ import annotations

import argparse
import json
import os

_HERE = os.path.dirname(__file__)
DATA = os.path.join(_HERE, "..", "data")

# --- multifile templates: each returns (files, task, gold_line) given an index -----------------
# Every template embeds a cross-file dependency, so the fix requires reading more than one file —
# which is exactly what the mctp condition should transfer and the transcript must carry whole.


def _mf_cache_invalidation(i):
    svc, cache = f"Service{i}", f"Cache{i}"
    files = {
        f"app/cache_{i}.py": f"class {cache}:\n    def __init__(self):\n        self._d = {{}}\n"
                             f"    def get(self, k):\n        return self._d.get(k)\n"
                             f"    def invalidate(self):\n        self._d.clear()\n",
        f"app/service_{i}.py": f"from app.cache_{i} import {cache}\n\nclass {svc}:\n"
                               f"    def __init__(self):\n        self.cache = {cache}()\n"
                               f"    def reload(self):\n        self._load()\n",
    }
    task = (f"After {svc}.reload() runs, stale values are still served from the cache. Give the "
            f"corrected line to append to reload() so the cache is invalidated on reload.")
    return files, task, "self.cache.invalidate()"


def _mf_missing_call(i):
    a, b = f"validate_{i}", f"handle_{i}"
    files = {
        f"lib/validate_{i}.py": f"def {a}(req):\n    if not req.get('token'):\n"
                                f"        raise ValueError('no token')\n    return True\n",
        f"lib/handler_{i}.py": f"from lib.validate_{i} import {a}\n\ndef {b}(req):\n"
                               f"    # missing validation\n    return process(req)\n",
    }
    task = (f"{b}() in handler_{i}.py processes requests without validating them, though "
            f"{a}() exists for that. Give the corrected line to add as the first line of {b}().")
    return files, task, f"{a}(req)"


def _mf_wrong_constant(i):
    files = {
        f"config/limits_{i}.py": f"MAX_RETRIES = 5\nTIMEOUT_S = 30\n",
        f"app/client_{i}.py": f"from config.limits_{i} import MAX_RETRIES, TIMEOUT_S\n\n"
                              f"def call():\n    for attempt in range(3):  # should use MAX_RETRIES\n"
                              f"        try:\n            return do()\n        except Exception:\n"
                              f"            continue\n",
    }
    task = (f"call() in client_{i}.py hard-codes 3 retries but config/limits_{i}.py defines "
            f"MAX_RETRIES. Give the corrected for-loop line that uses the configured value.")
    return files, task, "for attempt in range(MAX_RETRIES):"


_MF_TEMPLATES = [_mf_cache_invalidation, _mf_missing_call, _mf_wrong_constant]


def gen_multifile(n):
    rows = []
    for i in range(n):
        files, task, gold = _MF_TEMPLATES[i % len(_MF_TEMPLATES)](i)
        rows.append({"task_id": f"multifile/gen-{i}", "files": files, "task": task,
                     "gold_line": gold, "synthetic": True})
    return rows


# --- swarm templates: each returns a pipeline spec (brief + stages) ----------------------------
# The engineer stage carries an objective check embedded as asserts the runner executes.

def _swarm_task(i, name, brief, spec, asserts):
    return {"task_id": f"swarm/gen-{i}-{name}", "brief": brief, "spec_name": spec,
            "asserts": asserts, "synthetic": True}


_SWARM_SPECS = [
    ("slugify", "Add slugify(text): lowercase, replace non-alphanumeric runs with a single "
     "hyphen, strip leading/trailing hyphens.",
     ["assert slugify('Hello World!') == 'hello-world'",
      "assert slugify('  A..B  ') == 'a-b'",
      "assert slugify('already-slug') == 'already-slug'"]),
    ("chunk", "Add chunk(items, size): split a list into consecutive sublists of length size "
     "(the last may be shorter).",
     ["assert chunk([1,2,3,4,5], 2) == [[1,2],[3,4],[5]]",
      "assert chunk([], 3) == []",
      "assert chunk([1], 5) == [[1]]"]),
    ("dedupe", "Add dedupe(items): return items with duplicates removed, preserving first-seen "
     "order.",
     ["assert dedupe([3,1,3,2,1]) == [3,1,2]",
      "assert dedupe([]) == []",
      "assert dedupe(['a','a','b']) == ['a','b']"]),
]


def gen_swarm(n):
    rows = []
    for i in range(n):
        name, brief, asserts = _SWARM_SPECS[i % len(_SWARM_SPECS)]
        fn = name
        rows.append(_swarm_task(i, name, brief, fn, asserts))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True, choices=["multifile", "swarm"])
    ap.add_argument("--n", type=int, default=300)
    args = ap.parse_args()
    os.makedirs(DATA, exist_ok=True)
    rows = gen_multifile(args.n) if args.suite == "multifile" else gen_swarm(args.n)
    path = os.path.join(DATA, f"{args.suite}.jsonl")
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} synthetic {args.suite} tasks -> {os.path.relpath(path)}")


if __name__ == "__main__":
    main()
