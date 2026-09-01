#!/usr/bin/env python3
"""Unified status view for a benchmark store.

Reads a results directory directly (no telemetry socket) and reports total progress
across every model, suite, and condition present. Because all workers write to the same
store, this is the single place to watch the whole benchmark regardless of how many
machines are feeding it.

  python status.py                       one-shot snapshot of ./results
  python status.py --results results     point at a specific store
  python status.py --watch               redraw every few seconds
  python status.py --expect 47000        add overall %-complete and ETA at current rate
"""
import argparse
import glob
import json
import os
import sys
import time
from collections import defaultdict


def scan(root):
    """Walk runs/<suite>/<model>/<condition>.jsonl and tally pass/fail/none/error."""
    cells = defaultdict(lambda: defaultdict(int))  # (model, suite) -> {pass,fail,none,error,total}
    per_cond = defaultdict(int)
    total = 0
    runs_glob = os.path.join(root, "runs", "*", "*", "*.jsonl")
    for path in glob.glob(runs_glob):
        parts = path.split(os.sep)
        suite, model = parts[-3], parts[-2]
        condition = os.path.basename(path)[:-6]
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    total += 1
                    per_cond[condition] += 1
                    cell = cells[(model, suite)]
                    cell["total"] += 1
                    try:
                        rec = json.loads(line)
                        op = rec.get("objective_pass")
                        v = "pass" if op is True else "fail" if op is False else "none"
                    except Exception:
                        v = "error"
                    cell[v] += 1
        except FileNotFoundError:
            continue
    return cells, per_cond, total


def throughput(root, window=120):
    """Runs written in the last `window` seconds, inferred from raw-capture mtimes."""
    now = time.time()
    n = 0
    for p in glob.glob(os.path.join(root, "raw", "*.jsonl")):
        try:
            if now - os.path.getmtime(p) <= window:
                n += 1
        except OSError:
            continue
    return n, window


def render(root, expect=None):
    cells, per_cond, total = scan(root)
    lines = []
    lines.append(f"benchmark store: {os.path.abspath(root)}")
    lines.append(time.strftime("  %Y-%m-%d %H:%M:%S"))
    lines.append("")

    # Per model x suite.
    models = sorted({m for (m, _s) in cells})
    for model in models:
        msuites = sorted(s for (m, s) in cells if m == model)
        mtotal = sum(cells[(model, s)]["total"] for s in msuites)
        mpass = sum(cells[(model, s)]["pass"] for s in msuites)
        rate = (100.0 * mpass / mtotal) if mtotal else 0.0
        lines.append(f"{model:28s} {mtotal:>7d} runs   pass {rate:5.1f}%")
        for s in msuites:
            c = cells[(model, s)]
            r = (100.0 * c["pass"] / c["total"]) if c["total"] else 0.0
            extra = ""
            if c["error"]:
                extra += f"  err {c['error']}"
            if c["none"]:
                extra += f"  none {c['none']}"
            lines.append(f"    {s:22s} {c['total']:>6d}   pass {r:5.1f}%{extra}")
        lines.append("")

    tp, win = throughput(root)
    rpm = tp * 60.0 / win
    lines.append(f"TOTAL recorded: {total:>7d} runs")
    if per_cond:
        conds = "  ".join(f"{k}={v}" for k, v in sorted(per_cond.items()))
        lines.append(f"by condition:   {conds}")
    lines.append(f"throughput:     {tp} runs in last {win}s  (~{rpm:.0f}/min)")
    if expect:
        pct = 100.0 * total / expect
        remaining = max(0, expect - total)
        eta_min = (remaining / rpm) if rpm > 0 else float("inf")
        eta = f"{eta_min/60:.1f} h" if eta_min != float("inf") else "stalled"
        lines.append(f"plan:           {total}/{expect}  ({pct:.1f}%)   ETA ~{eta} at current rate")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--expect", type=int, default=None)
    args = ap.parse_args()

    if not args.watch:
        print(render(args.results, args.expect))
        return
    try:
        while True:
            out = render(args.results, args.expect)
            sys.stdout.write("\x1b[2J\x1b[H")  # clear + home
            sys.stdout.write(out + "\n")
            sys.stdout.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
