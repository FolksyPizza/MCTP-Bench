#!/usr/bin/env python3
"""Convert standard benchmark datasets into the JSONL schemas the adapters expect.

Run on the host after setup_host.sh (needs the `datasets` library). Writes into data/:

    mbpp      -> data/mbpp.jsonl        (task_id, text, code, test_list, test_setup_code)
    gsm8k     -> data/gsm8k.jsonl       (question, answer)
    longbench -> data/longbench.jsonl   (_id, task, input, context, answers)
    swebench  -> data/swebench.jsonl    (instance_id, problem_statement, repo, base_commit,
                                         patch, test_patch, FAIL_TO_PASS, PASS_TO_PASS)

    python scripts/prepare_datasets.py --suite mbpp gsm8k longbench --limit 500

HumanEval comes from scripts/fetch_datasets.sh (a direct download), not this script.

Two suites need more than a field remap and are not produced here:
- swebench `files`: SWE-bench ships repo + base_commit, not a file snapshot. This script writes
  the metadata; the `files` map for each instance must be materialized by checking out
  repo@base_commit (a separate step). Until then the swebench adapter skips instances with no
  `files`, so metadata alone yields no runs.
- repobench: its cross-file context does not map one-to-one onto our {files, target_file, prefix,
  gold_line} schema; it needs a dataset-specific assembler, added later.
"""
from __future__ import annotations

import argparse
import json
import os

_HERE = os.path.dirname(__file__)
DATA = os.path.join(_HERE, "..", "data")

# LongBench QA-style configs our any-answer scorer can grade; others would be judge-only.
_LONGBENCH_CONFIGS = ["multifieldqa_en", "narrativeqa", "qasper", "hotpotqa", "2wikimqa",
                      "musique", "triviaqa"]


def _write(name: str, rows: list):
    path = os.path.join(DATA, f"{name}.jsonl")
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"  wrote {len(rows)} -> {os.path.relpath(path)}")


def prepare_mbpp(limit):
    from datasets import load_dataset
    ds = load_dataset("mbpp", split="test")
    rows = [{"task_id": r["task_id"], "text": r["text"], "code": r["code"],
             "test_list": r["test_list"], "test_setup_code": r.get("test_setup_code", "")}
            for r in ds]
    _write("mbpp", rows[:limit] if limit else rows)


def prepare_gsm8k(limit):
    from datasets import load_dataset
    ds = load_dataset("gsm8k", "main", split="test")
    rows = [{"question": r["question"], "answer": r["answer"]} for r in ds]
    _write("gsm8k", rows[:limit] if limit else rows)


def prepare_longbench(limit):
    from datasets import load_dataset
    per_config = max(1, (limit or 700) // len(_LONGBENCH_CONFIGS))
    rows = []
    for cfg in _LONGBENCH_CONFIGS:
        try:
            ds = load_dataset("THUDM/LongBench", cfg, split="test")
        except Exception as e:  # a config may be unavailable; keep going
            print(f"  (skip longbench:{cfg}: {type(e).__name__})")
            continue
        for i, r in enumerate(ds):
            if i >= per_config:
                break
            rows.append({"_id": r.get("_id", f"{cfg}-{i}"), "task": cfg,
                         "input": r["input"], "context": r["context"],
                         "answers": r.get("answers", [])})
    _write("longbench", rows)


def prepare_swebench(limit):
    from datasets import load_dataset
    ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    rows = []
    for r in ds:
        rows.append({"instance_id": r["instance_id"], "problem_statement": r["problem_statement"],
                     "repo": r["repo"], "base_commit": r["base_commit"], "patch": r["patch"],
                     "test_patch": r["test_patch"], "FAIL_TO_PASS": r["FAIL_TO_PASS"],
                     "PASS_TO_PASS": r["PASS_TO_PASS"]})
        if limit and len(rows) >= limit:
            break
    _write("swebench", rows)
    print("  NOTE: swebench needs a `files` snapshot per instance (checkout repo@base_commit); "
          "metadata alone yields no runs until that step is added.")


PREPARERS = {"mbpp": prepare_mbpp, "gsm8k": prepare_gsm8k, "longbench": prepare_longbench,
             "swebench": prepare_swebench}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", nargs="+", default=list(PREPARERS),
                    choices=list(PREPARERS), help="which datasets to prepare")
    ap.add_argument("--limit", type=int, default=None, help="cap examples per suite")
    args = ap.parse_args()
    os.makedirs(DATA, exist_ok=True)
    for suite in args.suite:
        print(f"preparing {suite} ...")
        try:
            PREPARERS[suite](args.limit)
        except Exception as e:
            print(f"  FAILED {suite}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
