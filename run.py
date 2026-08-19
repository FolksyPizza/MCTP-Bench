#!/usr/bin/env python3
"""MCTP-Bench CLI.

    python3 run.py                     # MockRunner over all scenarios x conditions
    python3 run.py --real              # additionally include recorded model-in-the-loop episodes
    python3 run.py --tokenizer NAME    # count tokens with a specific tokenizer
    python3 run.py --compare-tokenizers  # per-scenario token counts under every tokenizer

Token counts use the default tokenizer (tiktoken:o200k_base when available, else the
heuristic). tiktoken lives in the repository virtualenv, so use `.venv/bin/python run.py` to
count with real tokenizers. Writes results/episodes.jsonl.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import mctpbench  # noqa: E402  (path bootstrap)
from mctpbench import tokenizers  # noqa: E402
from mctpbench.conditions import make_context, tokens  # noqa: E402
from mctpbench.episode import append_jsonl, read_jsonl  # noqa: E402
from mctpbench.harness import record_real, run_episode  # noqa: E402
from mctpbench.runner import MockRunner  # noqa: E402
from mctpbench.scoring import report  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scenarios"))
from bug43 import scenario as bug43  # noqa: E402
from cache_staleness import scenario as cache_staleness  # noqa: E402
from auth_migration import scenario as auth_migration  # noqa: E402
from artifact_selection import scenario as artifact_selection  # noqa: E402
from payment_idempotency import scenario as payment_idempotency  # noqa: E402

RESULTS = os.path.join(os.path.dirname(__file__), "results", "episodes.jsonl")
SCENARIOS = [bug43, cache_staleness, auth_migration, artifact_selection, payment_idempotency]
CONDITIONS = ["flat", "mctp"]

_C_BUG = {"mechanism_leases": True, "ordering_before_copy": True, "rejected_locking": True}
_C_CACHE = {"mechanism_versioned": True, "read_version_check": True, "rejected_ttl": True}
_C_AUTH = {"mechanism_jwt": True, "revocation_refresh": True, "rejected_sessions": True}
_C_ARTIFACT = {"correct_value": True, "correct_location": True}
_C_PAYMENT = {"mechanism_idempotency": True, "check_before_charge": True,
              "rejected_alternatives": True}

# Observed Claude-subagent runs: (scenario, condition, retrieved_ids, passed, criteria).
# Token counts are computed from the scenario contexts under the selected tokenizer.
REAL_RUNS = [
    (bug43, "flat", [], True, _C_BUG),
    (bug43, "mctp", ["art_nodetransfer"], True, _C_BUG),
    (cache_staleness, "flat", [], True, _C_CACHE),
    (cache_staleness, "mctp", ["art_cacheclient", "art_versionstore"], True, _C_CACHE),
    (auth_migration, "flat", [], True, _C_AUTH),
    (auth_migration, "mctp", ["art_authmiddleware", "art_tokenservice"], True,
     {**_C_AUTH, "rejected_sub_alternative_lost": True}),
    (artifact_selection, "flat", [], True, _C_ARTIFACT),
    (artifact_selection, "mctp", ["art_dbconfig"], True, _C_ARTIFACT),
    (payment_idempotency, "flat", [], True, _C_PAYMENT),
    (payment_idempotency, "mctp", ["art_controller", "art_idempotency"], True,
     {**_C_PAYMENT, "rejected_detail_lost": True}),
]


def compare_tokenizers():
    toks = tokenizers.available()
    hdr = f"{'scenario':<20} {'cond':<5} " + " ".join(f"{t.replace('tiktoken:',''):>12}" for t in toks)
    print(hdr)
    print("-" * len(hdr))
    for scn in SCENARIOS:
        for cond in CONDITIONS:
            ctx, retrievable, _ids, _g, _t = make_context(scn, cond)
            full = ctx + "".join(retrievable.values())  # context + all retrievable source
            counts = " ".join(f"{tokens(full, t):>12}" for t in toks)
            print(f"{scn.name:<20} {cond:<5} {counts}")
    print("\n(counts = delivered context + all retrievable artifact source)")


def main():
    args = sys.argv[1:]
    if "--compare-tokenizers" in args:
        compare_tokenizers()
        return

    tok = tokenizers.default()
    if "--tokenizer" in args:
        tok = args[args.index("--tokenizer") + 1]

    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    open(RESULTS, "w").close()

    episodes = [run_episode(scn, cond, MockRunner(), tok)
                for scn in SCENARIOS for cond in CONDITIONS]
    if "--real" in args:
        episodes += [record_real(scn, cond, "claude-subagent", tok,
                                 retrieved_ids=rids, passed=passed, criteria=crit)
                     for scn, cond, rids, passed, crit in REAL_RUNS]

    append_jsonl(RESULTS, episodes)
    print(f"tokenizer: {tok}\n")
    print(report(read_jsonl(RESULTS)))
    print(f"\n{len(episodes)} episodes -> {os.path.relpath(RESULTS)}")


if __name__ == "__main__":
    main()
