#!/usr/bin/env python3
"""Re-score recorded runs of a suite in place, using the current scorer.

Uses each run's recorded gold (objective_detail) and its recorded output (output_ref), so no model
calls are needed. Currently supports longbench (QA answer matching), whose scorer was made robust
to markdown, punctuation, and rewording. Rewrites objective_pass and objective_detail; makes a
`.bak` of each shard it changes.

    python3 scripts/rescore.py --results <results-dir> --suite longbench
"""
import argparse
import glob
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from adapters.longbench import _any_match  # noqa: E402


def _read_output(results, ref):
    if not ref:
        return ""
    path = ref if os.path.isabs(ref) else os.path.join(results, ref)
    return open(path, errors="replace").read() if os.path.exists(path) else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--suite", default="longbench", choices=["longbench"])
    args = ap.parse_args()

    shards = glob.glob(os.path.join(args.results, "runs", args.suite, "*", "*.jsonl"))
    total = changed = 0
    for path in shards:
        out_lines, dirty = [], False
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            total += 1
            det = r.get("objective_detail") or {}
            answers = det.get("answers")
            if not answers or not r.get("output_ref"):
                out_lines.append(json.dumps(r))
                continue
            ok, new_det = _any_match(answers)(_read_output(args.results, r.get("output_ref")))
            if bool(r.get("objective_pass")) != bool(ok) or r.get("objective_detail") != new_det:
                r["objective_pass"] = ok
                r["objective_detail"] = new_det
                changed += 1
                dirty = True
            out_lines.append(json.dumps(r))
        if dirty:
            shutil.copy2(path, path + ".bak")
            with open(path, "w") as f:
                f.write("\n".join(out_lines) + "\n")
    print(f"rescored {args.suite}: {changed} changed / {total} runs across {len(shards)} shards")


if __name__ == "__main__":
    main()
