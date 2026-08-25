#!/usr/bin/env python3
"""Analysis pass: aggregate the stored run records and apply pricing.

Reads results/runs/**, optionally folds in the ensemble judge labels from results/judge/, and
writes committed tables to results/aggregates/. Cost is computed here, not stored: token counts
live in the records and a pricing table is applied at analysis time, so prices can change
without re-running anything.

    python analyze.py [--results DIR] [--pricing pricing.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict

_HERE = os.path.dirname(__file__)

# USD per 1M tokens (input, output). A stand-in table; override with --pricing. Local open
# models have no market price — these are illustrative equivalents for cross-condition cost.
DEFAULT_PRICING = {
    "_default": {"input": 0.20, "output": 0.60},
}


def _load_runs(root: str) -> list:
    out = []
    for path in glob.glob(os.path.join(root, "runs", "*", "*", "*.jsonl")):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


def _load_judge(root: str) -> dict:
    out = {}
    for path in glob.glob(os.path.join(root, "judge", "*.json")):
        with open(path) as f:
            j = json.load(f)
            out[j["run_id"]] = j
    return out


def _price(model: str, pricing: dict) -> dict:
    return pricing.get(model, pricing.get("_default", {"input": 0.0, "output": 0.0}))


def _ref_total(rec: dict) -> tuple:
    """Fall back to reference token counts when native usage is absent (e.g. dry runs)."""
    ref = rec.get("ref_token_counts") or {}
    if not ref:
        return 0, 0
    enc = next(iter(ref.values()))
    return enc.get("prompt", 0), enc.get("output", 0) + enc.get("reasoning", 0)


def cost(rec: dict, pricing: dict) -> float:
    p = _price(rec["model"], pricing)
    inp = rec.get("prompt_tokens", 0)
    outp = rec.get("output_tokens", 0) + rec.get("reasoning_tokens", 0)
    if not (inp or outp):
        inp, outp = _ref_total(rec)
    inp += rec.get("prep_tokens", 0)          # summarizer/retrieval preparation
    return inp / 1e6 * p["input"] + outp / 1e6 * p["output"]


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def aggregate(runs: list, judge: dict, pricing: dict) -> list:
    groups = defaultdict(list)
    for r in runs:
        groups[(r["suite"], r["model"], r["condition"])].append(r)

    rows = []
    for (suite, model, condition), recs in sorted(groups.items()):
        obj = [r["objective_pass"] for r in recs if r.get("objective_pass") is not None]
        jud = [judge[r["run_id"]]["final_pass"] for r in recs
               if r["run_id"] in judge and judge[r["run_id"]].get("final_pass") is not None]
        rows.append({
            "suite": suite, "model": model, "condition": condition, "n": len(recs),
            "objective_pass_rate": (sum(obj) / len(obj)) if obj else None,
            "judge_pass_rate": (sum(jud) / len(jud)) if jud else None,
            "avg_context_tokens": round(_avg(r["context_tokens"] for r in recs), 1),
            "avg_context_original": round(_avg(
                r.get("context_tokens_original") or r["context_tokens"] for r in recs), 1),
            "truncation_rate": round(_avg(
                1.0 if r.get("context_truncated") else 0.0 for r in recs), 3),
            "avg_output_tokens": round(_avg(
                (r.get("output_tokens") or 0) + (r.get("reasoning_tokens") or 0)
                for r in recs), 1),
            "avg_latency_s": round(_avg(r["latency_s"] for r in recs), 2),
            "avg_cost_usd": round(_avg(cost(r, pricing) for r in recs), 6),
        })
    return rows


def _table(rows: list) -> str:
    cols = ["suite", "model", "condition", "n", "objective_pass_rate", "judge_pass_rate",
            "avg_context_tokens", "avg_context_original", "truncation_rate",
            "avg_output_tokens", "avg_latency_s", "avg_cost_usd"]
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = [head, sep]
    for r in rows:
        vals = []
        for c in cols:
            v = r[c]
            if isinstance(v, float) and c.endswith("rate"):
                v = f"{v*100:.0f}%"
            elif v is None:
                v = "-"
            vals.append(str(v))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(_HERE, "results"))
    ap.add_argument("--pricing", default=None)
    args = ap.parse_args()

    pricing = DEFAULT_PRICING
    if args.pricing and os.path.exists(args.pricing):
        with open(args.pricing) as f:
            pricing = json.load(f)

    runs = _load_runs(args.results)
    judge = _load_judge(args.results)
    rows = aggregate(runs, judge, pricing)

    agg_dir = os.path.join(args.results, "aggregates")
    os.makedirs(agg_dir, exist_ok=True)
    with open(os.path.join(agg_dir, "summary.json"), "w") as f:
        json.dump({"pricing": pricing, "rows": rows}, f, indent=2)
    table = _table(rows)
    with open(os.path.join(agg_dir, "summary.md"), "w") as f:
        f.write("# MCTP-Bench results summary\n\n")
        f.write(f"{len(runs)} runs, {len(judge)} judged.\n\n")
        f.write(table + "\n")
    print(table)
    print(f"\n{len(runs)} runs, {len(judge)} judged -> {os.path.relpath(agg_dir)}/summary.{{md,json}}")


if __name__ == "__main__":
    main()
