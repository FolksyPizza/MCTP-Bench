"""Aggregate episodes into a report grouped by (scenario, condition, runner)."""
from __future__ import annotations

from collections import defaultdict


def _avg(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def report(episodes) -> str:
    """episodes: list of dicts (from Episode.to_json / read_jsonl)."""
    groups = defaultdict(list)
    for e in episodes:
        groups[(e["scenario"], e["condition"], e["runner"])].append(e)

    lines = []
    hdr = (f"{'scenario':<10} {'cond':<5} {'runner':<16} {'n':>2} "
           f"{'pass%':>6} {'ctx_tok':>8} {'ret_tok':>8} {'tot_tok':>8} "
           f"{'pulls':>6} {'cb_reads':>8} {'mislead':>7}")
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for (scn, cond, runner), eps in sorted(groups.items()):
        n = len(eps)
        lines.append(
            f"{scn:<10} {cond:<5} {runner:<16} {n:>2} "
            f"{100*_avg(e['outcome_pass'] for e in eps):>5.0f}% "
            f"{_avg(e['context_tokens'] for e in eps):>8.0f} "
            f"{_avg(e['retrieved_tokens'] for e in eps):>8.0f} "
            f"{_avg(e['total_tokens'] for e in eps):>8.0f} "
            f"{_avg(len(e['retrieved_ids']) for e in eps):>6.1f} "
            f"{_avg(e['codebase_reads'] for e in eps):>8.1f} "
            f"{sum(e['misleading'] for e in eps):>7}")
    return "\n".join(lines)
