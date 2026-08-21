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
from mctpbench.runner import MockRunner, OpenAICompatRunner  # noqa: E402
from mctpbench.scoring import report  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scenarios"))
from bug43 import scenario as bug43  # noqa: E402
from cache_staleness import scenario as cache_staleness  # noqa: E402
from auth_migration import scenario as auth_migration  # noqa: E402
from artifact_selection import scenario as artifact_selection  # noqa: E402
from payment_idempotency import scenario as payment_idempotency  # noqa: E402
from schema_migration import scenario as schema_migration  # noqa: E402
from api_versioning import scenario as api_versioning  # noqa: E402
from flaky_test import scenario as flaky_test  # noqa: E402
from hidden_constraint import scenario as hidden_constraint  # noqa: E402
from outage_investigation import scenario as outage_investigation  # noqa: E402

RESULTS = os.path.join(os.path.dirname(__file__), "results", "episodes.jsonl")
SCENARIOS = [bug43, cache_staleness, auth_migration, artifact_selection, payment_idempotency,
             schema_migration, api_versioning, flaky_test, hidden_constraint,
             outage_investigation]
CONDITIONS = ["flat", "mctp"]

_C_BUG = {"mechanism_leases": True, "ordering_before_copy": True, "rejected_locking": True}
_C_CACHE = {"mechanism_versioned": True, "read_version_check": True, "rejected_ttl": True}
_C_AUTH = {"mechanism_jwt": True, "revocation_refresh": True, "rejected_sessions": True}
_C_ARTIFACT = {"correct_value": True, "correct_location": True}
_C_PAYMENT = {"mechanism_idempotency": True, "check_before_charge": True,
              "rejected_alternatives": True}
_C_SCHEMA = {"expand_contract": True, "later_constraint": True, "rejected_blocking": True}
_C_API = {"mechanism_bearer_header": True, "rejected_query_token": True}
_C_FLAKY = {"mechanism_clock": True, "root_cause_now": True, "rejected_bandaids": True}
_C_OUTAGE = {"mechanism_singleflight": True, "breaker_rate": True, "rejected_scale_timeout": True}

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
    (schema_migration, "flat", [], True, _C_SCHEMA),
    (schema_migration, "mctp", ["art_migration", "art_backfill", "art_orders"], True, _C_SCHEMA),
    (api_versioning, "flat", [], True, _C_API),
    (api_versioning, "mctp", [], True, _C_API),
    (flaky_test, "flat", [], True, _C_FLAKY),
    (flaky_test, "mctp", ["art_service", "art_clock", "art_test"], True, _C_FLAKY),
    (hidden_constraint, "flat", [], True, {"respects_soft_delete": True, "mechanism_bulk": True}),
    # The packet omitted the soft-delete constraint (an extraction-linking miss), so the mctp
    # agent could not determine the required deletion path and abstained: a genuine MCTP failure.
    (hidden_constraint, "mctp", [], False,
     {"respects_soft_delete": False, "mechanism_bulk": True}),
    (outage_investigation, "flat", [], True, _C_OUTAGE),
    (outage_investigation, "mctp",
     ["art_cacheread", "art_breaker", "art_retry", "art_origin"], True, _C_OUTAGE),
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


def _arg(args, name, default=None):
    i = args.index(name) if name in args else -1
    return args[i + 1] if 0 <= i < len(args) - 1 else default


def run_model(args, model, tok):
    """Sweep every scenario x condition (x trials) through a real OpenAI-compatible model and
    append the episodes to results/model_runs.jsonl (kept separate from the curated data)."""
    runner = OpenAICompatRunner(base_url=_arg(args, "--url"), model=model,
                                api_key=_arg(args, "--api-key"),
                                max_tokens=_arg(args, "--max-tokens"))
    trials = int(_arg(args, "--trials", "1"))
    limit = _arg(args, "--limit")
    scenarios = SCENARIOS[: int(limit)] if limit else SCENARIOS
    out = os.path.join(os.path.dirname(RESULTS), "model_runs.jsonl")

    print(f"runner: {runner.name}  url: {runner.base_url}  tokenizer: {tok}  trials: {trials}\n")
    episodes = []
    for scn in scenarios:
        for cond in CONDITIONS:
            for t in range(trials):
                try:
                    ep = run_episode(scn, cond, runner, tok)
                    episodes.append(ep)
                    print(f"  {scn.name:22} {cond:5} t{t + 1}: "
                          f"{'pass' if ep.outcome_pass else 'FAIL'} "
                          f"ctx={ep.context_tokens} ret={ep.retrieved_tokens} "
                          f"pulls={len(ep.retrieved_ids)}")
                except Exception as e:  # network/endpoint/parse errors: log and continue
                    print(f"  {scn.name:22} {cond:5} t{t + 1}: ERROR {type(e).__name__}: {e}")
    append_jsonl(out, episodes)
    print()
    print(report([e.to_json() for e in episodes]))
    print(f"\n{len(episodes)} episodes -> {os.path.relpath(out)}")


def main():
    args = sys.argv[1:]
    if "--compare-tokenizers" in args:
        compare_tokenizers()
        return

    tok = _arg(args, "--tokenizer") or tokenizers.default()

    model = _arg(args, "--model")
    if model:
        run_model(args, model, tok)
        return

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
