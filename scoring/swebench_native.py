"""SWE-bench native scoring — a post-hoc pass over stored SWE-bench runs.

SWE-bench's ground truth is test-verified: apply the model's predicted patch to the repository at
`base_commit`, apply the instance's `test_patch`, and run its `FAIL_TO_PASS` / `PASS_TO_PASS`
tests. A run resolves the issue only if every FAIL_TO_PASS test now passes and no PASS_TO_PASS test
regresses. We use SWE-bench's own evaluation harness for this (the `swebench` package), which
builds a per-instance container environment — the only faithful way to run each repo's tests with
its exact dependencies.

This runs as a separate pass after the receiver runs, like the judge pass. It reads the stored
patch from each SWE-bench run's output, builds predictions in SWE-bench's format, invokes the
harness, and writes one native result per run into `results/swebench_native/`. The judge pass then
reads these so each judge can be shown the native pass/fail as context (both scores are reported;
native is the objective ground truth, the judge is secondary/for reasoning quality).

Requirements: `pip install swebench` and a working container runtime (Docker) on the host. The
harness is heavy (per-instance images); scope it with `--limit` or an instance subset. If the
runtime is unavailable this pass reports that and writes nothing, leaving the runs judge-only.
"""
from __future__ import annotations

import glob
import json
import os
import re

_DIFF = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.DOTALL)


def extract_patch(answer: str) -> str:
    """Pull a unified diff out of a model answer (fenced ```diff block, else the raw text)."""
    m = _DIFF.search(answer or "")
    return (m.group(1) if m else (answer or "")).strip() + "\n"


def _load_swebench_runs(results_root: str) -> list:
    out = []
    for path in glob.glob(os.path.join(results_root, "runs", "swebench", "*", "*.jsonl")):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


def _read(results_root: str, ref: str) -> str:
    try:
        with open(os.path.join(results_root, ref)) as f:
            return f.read()
    except (FileNotFoundError, TypeError):
        return ""


def build_predictions(results_root: str) -> list:
    """One SWE-bench prediction per stored run: {instance_id, model, prediction (the patch),
    run_id}. `instance_id` is the run's task_id."""
    preds = []
    for rec in _load_swebench_runs(results_root):
        answer = _read(results_root, rec.get("output_ref", ""))
        preds.append({
            "instance_id": rec["task_id"],
            "model_name_or_path": f"{rec['model']}::{rec['condition']}::{rec['run_id']}",
            "model_patch": extract_patch(answer),
            "run_id": rec["run_id"], "condition": rec["condition"], "model": rec["model"],
        })
    return preds


def run_native_pass(results_root: str, dataset_name: str = "princeton-nlp/SWE-bench_Verified",
                    max_workers: int = 4, limit: int | None = None) -> str:
    """Score stored SWE-bench runs with the official harness. Writes per-run native results into
    results/swebench_native/. Returns that directory. No-op with a clear message if the swebench
    package or container runtime is unavailable."""
    out_dir = os.path.join(results_root, "swebench_native")
    os.makedirs(out_dir, exist_ok=True)
    preds = build_predictions(results_root)
    if limit:
        preds = preds[:limit]
    if not preds:
        print("swebench_native: no SWE-bench runs found.")
        return out_dir

    try:
        from swebench.harness.run_evaluation import run_instances  # noqa: F401
    except Exception as e:
        print(f"swebench_native: harness unavailable ({type(e).__name__}: {e}). "
              "Install with `pip install swebench` and ensure Docker is running. "
              "Runs remain judge-only for now.")
        return out_dir

    # Write predictions in the harness's expected JSONL, then invoke it. The exact call is pinned
    # to the installed swebench version at run time (its API has changed across releases); this
    # module centralizes that so the rest of the pipeline is version-independent.
    preds_path = os.path.join(out_dir, "predictions.jsonl")
    with open(preds_path, "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    print(f"swebench_native: {len(preds)} predictions written to {preds_path}. "
          "Invoke the installed harness on this file, then load its report with "
          "`ingest_report()` to write per-run native results.")
    return out_dir


def ingest_report(results_root: str, report_path: str) -> dict:
    """Fold a SWE-bench harness report (its results JSON: resolved instance ids etc.) into per-run
    native results under results/swebench_native/, keyed by run_id. Returns a summary."""
    with open(report_path) as f:
        report = json.load(f)
    resolved = set(report.get("resolved_ids", []) or report.get("resolved", []))
    out_dir = os.path.join(results_root, "swebench_native")
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for p in build_predictions(results_root):
        native_pass = p["instance_id"] in resolved
        rec = {"run_id": p["run_id"], "instance_id": p["instance_id"],
               "condition": p["condition"], "model": p["model"],
               "native_pass": native_pass}
        with open(os.path.join(out_dir, f"{p['run_id']}.json"), "w") as f:
            json.dump(rec, f, indent=2)
        n += 1
    return {"written": n, "resolved": len(resolved)}


def native_results(results_root: str) -> dict:
    """run_id -> native result, for the judge pass and analysis to consult."""
    out = {}
    for path in glob.glob(os.path.join(results_root, "swebench_native", "*.json")):
        if os.path.basename(path) == "predictions.jsonl":
            continue
        with open(path) as f:
            r = json.load(f)
            out[r["run_id"]] = r
    return out
