#!/usr/bin/env python3
"""ASTP-Bench matrix runner.

Runs suite x models x conditions x trials, recording each run with full raw capture and parsed
fields into the results storage tree (see docs/DATA-MODEL.md). Objective scoring (unit tests /
exact match) runs at record time; the ensemble judge and pricing are separate later passes.

    # dry run (no server): validate the whole pipeline with the deterministic MockRunner
    python run_benchmark.py --suite humaneval --dry-run

    # real run against an OpenAI-compatible endpoint (vLLM / Ollama)
    python run_benchmark.py --suite humaneval --models qwen2.5-coder:14b \
        --conditions transcript,mctp --trials 3 --url http://localhost:8000/v1

Nothing contacts a model server unless --url and --models are given (and --dry-run is absent).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

sys.path.insert(0, os.path.dirname(__file__))

from adapters import get_adapter  # noqa: E402
from conditions import build  # noqa: E402
from mctpbench import telemetry, tokenizers  # noqa: E402
from mctpbench.orchestrate import (  # noqa: E402
    Manifest, Progress, StopController, WindowGate, run_key)
from mctpbench.records import ResultStore, RunRecord, new_run_id  # noqa: E402
from mctpbench.runner import MockRunner  # noqa: E402
from mctpbench.streaming import StreamingRunner  # noqa: E402

_HERE = os.path.dirname(__file__)


def _size_b(model: str):
    m = re.search(r"(\d+(?:\.\d+)?)\s*b\b", model.lower())
    return float(m.group(1)) if m else None


def _is_reasoning(model: str) -> bool:
    return bool(re.search(r"(qwen3|deepseek-r1|reason|think|o1|o3)", model.lower()))


def _tok(text: str, t: str) -> int:
    try:
        return tokenizers.count(text or "", t)
    except Exception:
        return 0


def execute_run(store, *, suite, task_id, tier, source, condition, model, trial, runner, tok,
                instruction=None, objective=None, summarizer=None, endpoint="", temperature=0.0,
                seed=1, max_tokens=None, max_context_tokens=0):
    """Build one condition's context, run the receiver, score, and record. Returns
    (RunRecord, answer_text). Reused by the matrix runner and the multi-handoff pipeline.

    `max_context_tokens` fits the context to the model window: anything larger is trimmed
    (head+tail) and flagged. A small mctp packet passes through untouched while a long transcript
    is trimmed, and that difference is recorded per run."""
    built = build(source, condition, summarizer=summarizer,
                  budget_tokens=(max_context_tokens or None))
    # When the packet carries artifact references (mctp), tell the receiver it can pull them —
    # the OSS suites' own instructions don't mention the RETRIEVE mechanism, so without this the
    # model never retrieves and the mctp condition is unfairly starved of context.
    q = instruction
    if built.retrievable:
        ids = " ".join(built.retrievable)
        q = (f"{instruction or ''}\n\nReferenced items available on demand: {ids}. If you need an "
             f"item's full contents to answer, reply with exactly one line: RETRIEVE <id> "
             f"[<id> ...] — the contents will then be provided and you can answer.")
    orig_context_tokens = _tok(built.text, tok)
    context_text, truncated = tokenizers.truncate_to_tokens(built.text, max_context_tokens)
    result = runner.run(task=source.task, context=context_text, retrievable=built.retrievable,
                        question=q)

    answer = result.answer
    reasoning = getattr(result, "reasoning", "") or ""
    prompt_text = getattr(result, "prompt_text", "") or built.text
    timeline = result.timeline() if hasattr(result, "timeline") else []
    native = result.native_tokens() if hasattr(result, "native_tokens") else {}

    retrieved = [i for i in result.retrieved_ids if i in built.retrievable]
    retrieved_tokens = sum(_tok(built.retrievable[i], tok) for i in retrieved)

    objective_pass, objective_detail = (None, {})
    if objective is not None:
        try:
            objective_pass, objective_detail = objective(answer)
        except Exception as e:  # a scorer crash must not lose the run
            objective_detail = {"scorer_error": f"{type(e).__name__}: {e}"}

    latency = getattr(result, "rounds", None) and result.rounds[-1].t_end or 0.0
    ttft = None
    if getattr(result, "rounds", None):
        ttft = next((r.ttft_s for r in result.rounds if r.ttft_s is not None), None)

    rec = RunRecord(
        run_id=new_run_id(), suite=suite, task_id=task_id, tier=tier,
        condition=condition, model=model, model_size_b=_size_b(model),
        reasoning=_is_reasoning(model), trial=trial,
        started_at=_iso(getattr(result, "started_at", 0.0)),
        context_tokens=_tok(context_text, tok), context_truncated=truncated,
        context_tokens_original=orig_context_tokens, packet_node_ids=built.packet_node_ids,
        prep_tokens=built.prep_tokens,
        retrieved_ids=retrieved, retrieved_tokens=retrieved_tokens,
        codebase_reads=getattr(result, "codebase_reads", 0),
        prompt_tokens=native.get("prompt_tokens", 0),
        reasoning_tokens=native.get("reasoning_tokens", 0),
        output_tokens=native.get("output_tokens", 0),
        ttft_s=ttft, latency_s=latency,
        objective_pass=objective_pass, objective_detail=objective_detail,
        runner=getattr(runner, "name", "unknown"), endpoint=endpoint,
        temperature=temperature, seed=seed, max_tokens=max_tokens,
    )
    rec = store.write_run(rec, prompt=prompt_text, output=answer, reasoning=reasoning,
                          timeline=timeline, raw_result=result)
    return rec, answer


def run_one(store, adapter, task, condition, model, trial, runner, tok, *,
            summarizer=None, endpoint="", temperature=0.0, seed=1, max_tokens=None,
            max_context_tokens=0) -> RunRecord:
    rec, _ = execute_run(
        store, suite=adapter.name, task_id=task.task_id, tier=task.source.tier,
        source=task.source, condition=condition, model=model, trial=trial, runner=runner,
        tok=tok, instruction=task.receiver_instruction, objective=task.objective,
        summarizer=summarizer, endpoint=endpoint, temperature=temperature, seed=seed,
        max_tokens=max_tokens, max_context_tokens=max_context_tokens)
    return rec


def _stop_ollama_models():
    """Stop every currently-loaded Ollama model, freeing the GPU (vLLM and Ollama can't share the
    cards here). Best-effort: prints and continues if the ollama CLI is absent."""
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10)
        names = [ln.split()[0] for ln in out.stdout.splitlines()[1:] if ln.split()]
        for name in names:
            subprocess.run(["ollama", "stop", name], timeout=30, capture_output=True)
        print(f"[stop-ollama] stopped {len(names)} model(s): {', '.join(names) or 'none'}")
    except Exception as e:
        print(f"[stop-ollama] skipped ({type(e).__name__}: {e})")


def _shell_hook(cmd):
    """A callable that runs a shell command (or None). Used for --on-pause / --on-resume so the
    model server can be stopped when the window closes and restarted when it reopens."""
    if not cmd:
        return None
    return lambda: subprocess.run(cmd, shell=True, check=False)


def _parse_models(spec: str, default_url: str) -> list:
    """Parse '--models' into [(model_id, endpoint_url)]. A model may carry its own endpoint as
    'model@http://host:port/v1'; bare models use default_url."""
    out = []
    for m in spec.split(","):
        m = m.strip()
        if not m:
            continue
        if "@" in m:
            name, url = m.split("@", 1)
            out.append((name.strip(), url.strip()))
        else:
            out.append((m, default_url))
    return out


def _iso(epoch: float) -> str:
    if not epoch:
        return ""
    import datetime
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat()


def main():
    ap = argparse.ArgumentParser(description="ASTP-Bench matrix runner")
    ap.add_argument("--suite", required=True,
                    help="humaneval | mbpp | gsm8k | swebench | repobench | longbench | "
                         "inhouse | swarm")
    ap.add_argument("--models", default="", help="comma-separated model ids")
    ap.add_argument("--conditions", default="", help="comma-separated; default: suite's set")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="first N tasks only")
    ap.add_argument("--url", default="http://localhost:8000/v1")
    ap.add_argument("--api-key", default="EMPTY")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--max-context-tokens", type=int, default=0,
                    help="trim a condition's context to this many tokens (head+tail) to fit the "
                         "model window; 0 = no trimming. Set below (window - max-tokens) for "
                         "high-context suites. Truncation is flagged per run.")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--results", default=os.path.join(_HERE, "results"))
    ap.add_argument("--tokenizer", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="deterministic MockRunner, no server contact")
    ap.add_argument("--resume", action="store_true",
                    help="skip runs already recorded in the checkpoint manifest")
    ap.add_argument("--window", default=None,
                    help="only run within a clock window, e.g. 23:00-06:00 (local time)")
    ap.add_argument("--max-hours", type=float, default=None,
                    help="stop cleanly after this many hours; --resume continues later")
    ap.add_argument("--progress-every", type=int, default=25,
                    help="print an ETA/progress line every N runs")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="number of runs in flight at once; >1 lets vLLM batch (use lower values "
                         "for long-context suites where KV cache caps the batch)")
    ap.add_argument("--retries", type=int, default=2,
                    help="retry a run this many times on a transient (network/5xx) error")
    ap.add_argument("--stop-ollama", action="store_true",
                    help="stop all loaded Ollama models at startup to free the GPU for vLLM")
    ap.add_argument("--arrangements", default="same,cross",
                    help="swarm only: agent arrangements to run — 'same' (one family per pipeline) "
                         "and/or 'cross' (different families across roles)")
    ap.add_argument("--telemetry-port", type=int, default=8765,
                    help="serve live telemetry on 127.0.0.1:<port> for monitor.py (0 disables)")
    ap.add_argument("--on-pause", default=None,
                    help="shell command run when a --window pause begins (e.g. stop vLLM to free "
                         "the GPU)")
    ap.add_argument("--on-resume", default=None,
                    help="shell command run when the window reopens (e.g. restart vLLM)")
    args = ap.parse_args()

    adapter = get_adapter(args.suite)
    conditions = (args.conditions.split(",") if args.conditions
                  else list(adapter.default_conditions))
    tok = args.tokenizer or tokenizers.default()
    store = ResultStore(args.results, harness_repo=_HERE)

    if args.dry_run or not args.models:
        models = ["mock"]
        url_of = {"mock": ""}
        make_runner = lambda _m: MockRunner()  # noqa: E731
        summarizer_for = lambda _r: None       # noqa: E731
        mode = "DRY RUN (MockRunner, no server)"
    else:
        # Each model may carry its own endpoint as `model@url`, so a sweep can fan out across
        # several vLLM servers (each vLLM process serves one model). Bare models use --url.
        specs = _parse_models(args.models, args.url)
        models = [name for name, _ in specs]
        url_of = dict(specs)
        make_runner = lambda m: StreamingRunner(  # noqa: E731
            base_url=url_of[m], model=m, api_key=args.api_key, max_tokens=args.max_tokens,
            temperature=args.temperature, seed=args.seed)
        summarizer_for = lambda r: r.summarize   # noqa: E731
        mode = "  ".join(f"{n}@{u}" for n, u in specs)

    tasks = list(adapter.tasks(limit=args.limit))

    # For swarm, the "model" dimension is the agent arrangement (which model plays each role);
    # for every other suite it is the model list.
    swarm_arrangements = None
    if args.suite == "swarm":
        from mctpbench.pipeline import build_arrangements
        arr = build_arrangements(models, kinds=tuple(k for k in args.arrangements.split(",") if k))
        swarm_arrangements = dict(arr)
        model_units = list(swarm_arrangements)
    else:
        model_units = models

    total = len(tasks) * len(model_units) * len(conditions) * args.trials
    print(f"suite={args.suite}  {mode}  conditions={conditions}  "
          f"tasks={len(tasks)}  trials={args.trials}  -> {total} runs  tokenizer={tok}")
    if swarm_arrangements:
        for name, sm in arr:
            print(f"    arrangement {name}: {' -> '.join(sm)}")
    print()

    store.write_config(f"{args.suite}_batch.json", {
        "suite": args.suite, "models": models, "endpoints": url_of, "conditions": conditions,
        "trials": args.trials, "limit": args.limit, "tokenizer": tok,
        "temperature": args.temperature, "seed": args.seed, "max_tokens": args.max_tokens,
    })

    tele = telemetry.start(port=args.telemetry_port) if args.telemetry_port else telemetry._NullTelemetry()
    tele.update(suite=args.suite, models=models, conditions=conditions, total=total,
                done=0, running=True, tallies={"pass": 0, "fail": 0, "none": 0, "error": 0})

    if args.stop_ollama and not args.dry_run:
        _stop_ollama_models()

    # Key the manifest by model as well as suite, so several workers (e.g. one per GPU,
    # each serving a different model) can share a single results store without their
    # resume logs colliding. Run records are already sharded by runs/<suite>/<model>/.
    _mtag = "__".join(m.replace("/", "-").replace(":", "-").replace("@", "-") for m in models) or "all"
    manifest = Manifest(os.path.join(args.results, "progress", f"{args.suite}__{_mtag}.log"))
    gate = WindowGate(args.window)
    jobs = [(m, task, c, tr) for m in model_units for task in tasks for c in conditions
            for tr in range(1, args.trials + 1)]
    pending = [(m, task, c, tr) for (m, task, c, tr) in jobs
               if not (args.resume and manifest.has(run_key(args.suite, task.task_id, c, m, tr)))]
    already = len(jobs) - len(pending)
    progress = Progress(total=total, done=already)
    if already:
        print(f"resume: {already}/{total} already recorded — skipping those\n")
    print(f"concurrency={args.concurrency}  retries={args.retries}\n")

    stop_file = os.path.join(args.results, "progress", f"{args.suite}.stop")
    stopper = StopController(stop_file).install()
    print(f"controls: resume={args.resume}  window={args.window or 'always'}  "
          f"pause/stop: Ctrl-C or `touch {os.path.relpath(stop_file)}`\n")

    stop_at = (time.monotonic() + args.max_hours * 3600) if args.max_hours else None
    stopped = False
    runners = {}
    tallies = {"pass": 0, "fail": 0, "none": 0, "error": 0}
    results_lock = threading.Lock()   # guards progress, tallies, manifest, printing, telemetry
    runners_lock = threading.Lock()   # guards lazy runner creation

    def get_runner(model):
        with runners_lock:
            r = runners.get(model)
            if r is None:
                r = make_runner(model)
                runners[model] = r
            return r

    def do_run(job):
        """Execute one job (a swarm pipeline or a single run), with retries, then record under
        the lock. A StreamingRunner has no shared mutable state, so one per model is shared safely
        across workers; the shared collectors (store shard, manifest, progress) are locked."""
        model, task, condition, trial = job   # for swarm, `model` is the arrangement name
        is_swarm = args.suite == "swarm"
        if not is_swarm:
            runner = get_runner(model)
            summ = summarizer_for(runner) if condition == "summary" else None
            endpoint = "" if args.dry_run else url_of[model]
        t0 = time.monotonic()
        for attempt in range(args.retries + 1):
            try:
                if is_swarm:
                    from mctpbench.pipeline import run_pipeline
                    stage_models = swarm_arrangements[model]
                    lead = get_runner(stage_models[0])
                    recs = run_pipeline(store, task, condition, stage_models[0], trial, lead, tok,
                                        endpoint="" if args.dry_run else url_of[stage_models[0]],
                                        temperature=args.temperature, seed=args.seed,
                                        max_tokens=args.max_tokens, stage_models=stage_models,
                                        runner_for=get_runner, arrangement=model,
                                        max_context_tokens=args.max_context_tokens)
                    objs = [r.objective_pass for r in recs]
                    obj = [("-" if o is None else "pass" if o else "FAIL") for o in objs]
                    outcome = ("fail" if any(o is False for o in objs)
                               else "pass" if any(objs) else "none")
                    line = (f"{task.task_id:22.22} {condition:10} {model:18.18} t{trial} "
                            f"stages={len(recs)} obj={obj}")
                    last = f"{task.task_id} {condition} {model} stages={len(recs)} {outcome}"
                else:
                    rec = run_one(store, adapter, task, condition, model, trial, runner, tok,
                                  summarizer=summ, endpoint=endpoint,
                                  temperature=args.temperature, seed=args.seed,
                                  max_tokens=args.max_tokens,
                                  max_context_tokens=args.max_context_tokens)
                    outcome = ("none" if rec.objective_pass is None
                               else "pass" if rec.objective_pass else "fail")
                    line = (f"{task.task_id:22.22} {condition:10} {model:18.18} t{trial} "
                            f"{outcome:4} ctx={rec.context_tokens} out_tok={rec.output_tokens} "
                            f"lat={rec.latency_s:.1f}s")
                    last = f"{task.task_id} {condition} {model} {outcome}"
                with results_lock:
                    manifest.add(run_key(args.suite, task.task_id, condition, model, trial))
                    progress.tick(time.monotonic() - t0)
                    tallies[outcome] += 1
                    print(f"  [{progress.done}/{total}] {line}")
                    tele.update(done=progress.done, remaining=progress.remaining(),
                                rate_s=round(progress.rate(), 2), eta_s=progress.eta_seconds(),
                                elapsed_s=round(time.monotonic() - progress.start, 1),
                                tallies=dict(tallies), last=last,
                                current={"model": model, "condition": condition,
                                         "task": task.task_id})
                    if args.progress_every and progress.done % args.progress_every == 0:
                        print(f"  -- {progress.line()}")
                return
            except Exception as e:  # transient endpoint error: back off and retry
                if attempt < args.retries:
                    time.sleep(2 ** attempt)
                    continue
                with results_lock:
                    tallies["error"] += 1
                    tele.update(tallies=dict(tallies),
                                last=f"{task.task_id} {condition} {model} ERROR {type(e).__name__}")
                    print(f"  [err] {task.task_id:22.22} {condition:10} {model:18.18} t{trial} "
                          f"ERROR {type(e).__name__}: {e}")
                return

    pause_hook = _shell_hook(args.on_pause)
    resume_hook = _shell_hook(args.on_resume)
    job_iter = iter(pending)
    exhausted = False
    futures = set()
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
            while True:
                while (not exhausted and not stopped and len(futures) < args.concurrency
                       and gate.is_open()):
                    if stopper.should_stop():
                        stopped = True
                        break
                    if stop_at and time.monotonic() >= stop_at:
                        print(f"\n[max-hours] reached {args.max_hours}h budget; draining "
                              f"in-flight runs, then stopping. Re-run with --resume to continue.")
                        stopped = True
                        break
                    job = next(job_iter, None)
                    if job is None:
                        exhausted = True
                        break
                    futures.add(ex.submit(do_run, job))
                if not futures:
                    if stopped or exhausted:
                        break
                    if not gate.is_open():   # window closed, nothing in flight: safe to unload
                        gate.wait_until_open(on_pause=pause_hook, on_resume=resume_hook)
                        continue
                    break
                done, futures = wait(futures, return_when=FIRST_COMPLETED)
                futures = set(futures)
    except KeyboardInterrupt:
        print("\n[aborted] waiting for in-flight runs to finish; checkpoint saved. "
              "Re-run with --resume to continue.")
        stopped = True
        for f in futures:
            f.result()   # let in-flight runs complete and record
    finally:
        manifest.close()
        stopper.clear_stop_file()
        stopper.restore()
        tele.update(running=False, stopped=stopped)
        tele.stop()

    if stopped:
        print("\n[stopped] checkpoint saved. Continue later with the same command plus --resume.")
    print(f"\n{progress.done}/{total} runs recorded"
          f"{' (stopped early)' if stopped else ''} -> {os.path.relpath(args.results)}/  "
          f"(runs/ raw/ outputs/ gitignored; aggregates/ configs/ committed)")


if __name__ == "__main__":
    main()
