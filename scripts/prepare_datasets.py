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

Two further steps handle the repository suites:
- `swebench_files` augments the SWE-bench metadata with a `files` snapshot per instance, by
  checking out repo@base_commit and reading the files the gold/test patch touches (git + network
  + disk; repos cached under data/_repo_cache/). Run it after `swebench`.
- `repobench` maps RepoBench to our {files, target_file, prefix, gold_line} schema, keeping the
  cross-file context as a companion pseudo-file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess

_HERE = os.path.dirname(__file__)
DATA = os.path.join(_HERE, "..", "data")
CACHE = os.path.join(DATA, "_repo_cache")

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


_DIFF_PATH = re.compile(r"^\+\+\+ b/(.+)$", re.M)


def _patch_files(*patches) -> list:
    """File paths touched by one or more unified diffs (the b/ side, excluding /dev/null)."""
    paths = []
    for patch in patches:
        for m in _DIFF_PATH.finditer(patch or ""):
            p = m.group(1).strip()
            if p and p != "/dev/null" and p not in paths:
                paths.append(p)
    return paths


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=600)


def _checkout(repo: str, base_commit: str) -> str:
    """Clone (cached) github.com/<repo> and check out base_commit. Returns the working dir."""
    os.makedirs(CACHE, exist_ok=True)
    dest = os.path.join(CACHE, repo.replace("/", "__"))
    if not os.path.isdir(os.path.join(dest, ".git")):
        _git("clone", f"https://github.com/{repo}.git", dest)
    r = _git("checkout", "-f", base_commit, cwd=dest)
    if r.returncode != 0:
        _git("fetch", "--all", cwd=dest)
        _git("checkout", "-f", base_commit, cwd=dest)
    return dest


def prepare_swebench_files(limit, max_file_kb=64):
    """Augment data/swebench.jsonl (metadata from prepare_swebench) with a `files` snapshot per
    instance: the files touched by the gold patch and test patch, read at base_commit. These are
    the files the receiver needs; the extractor turns them into MCTP state. Requires git + network
    + disk (repos are cached under data/_repo_cache/)."""
    src = os.path.join(DATA, "swebench.jsonl")
    if not os.path.exists(src):
        print("  run --suite swebench first (need the metadata)."); return
    rows = [json.loads(l) for l in open(src) if l.strip()]
    if limit:
        rows = rows[:limit]
    out = []
    for i, r in enumerate(rows):
        try:
            work = _checkout(r["repo"], r["base_commit"])
            files = {}
            for path in _patch_files(r.get("patch", ""), r.get("test_patch", "")):
                fp = os.path.join(work, path)
                if os.path.isfile(fp) and os.path.getsize(fp) <= max_file_kb * 1024:
                    with open(fp, errors="replace") as fh:
                        files[path] = fh.read()
            r["files"] = files
            out.append(r)
            print(f"  [{i+1}/{len(rows)}] {r['instance_id']}: {len(files)} files")
        except Exception as e:
            print(f"  [{i+1}/{len(rows)}] {r['instance_id']}: FAILED {type(e).__name__}: {e}")
            out.append(r)  # keep metadata even if checkout failed
    _write("swebench", out)


def prepare_repobench(limit):
    """Map a RepoBench (python) dataset to our schema: files, target_file, prefix, gold_line.
    RepoBench provides cross-file context as text plus the in-file prefix (`code`) and the target
    (`next_line`); we keep the context as a companion pseudo-file so the extractor and the other
    conditions see the cross-file material."""
    from datasets import load_dataset
    ds = load_dataset("tianyang/repobench_python_v1.1", split="cross_file_first")
    rows = []
    for i, r in enumerate(ds):
        if limit and i >= limit:
            break
        target = r.get("file_path", f"target_{i}.py")
        prefix = (r.get("import_statement", "") + "\n" + r.get("code", "")).strip() + "\n"
        rows.append({
            "task_id": f"repobench/{i}",
            "files": {target: prefix, "_repo_context.py": r.get("context", "")},
            "target_file": target, "prefix": prefix,
            "gold_line": (r.get("next_line", "") or "").strip(),
        })
    _write("repobench", rows)


PREPARERS = {"mbpp": prepare_mbpp, "gsm8k": prepare_gsm8k, "longbench": prepare_longbench,
             "swebench": prepare_swebench, "swebench_files": prepare_swebench_files,
             "repobench": prepare_repobench}


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
