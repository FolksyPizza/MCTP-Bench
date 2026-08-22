"""Objective scorers: run at record time, set `objective_pass`.

- `humaneval_scorer(problem)` returns a scorer that extracts the model's code and runs the
  problem's own unit tests, the standard HumanEval pass@1 check.
- `exact_match(gold)` is a normalized string-equality scorer for short-answer suites.

Executing model-generated code is done in a separate Python subprocess with a wall-clock
timeout and no arguments, so a hang or crash cannot take down the harness. It is NOT a security
sandbox: run untrusted completions only on a host where that is acceptable (the dedicated GPU
box). A stronger sandbox (container / seccomp) can replace `_run_python` without touching the
rest of the pipeline.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile


def extract_code(answer: str) -> str:
    """Pull a Python code body out of a model answer.

    Prefers a fenced ```python block; falls back to the first fenced block; otherwise returns
    the answer as-is (the model may have emitted bare code)."""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", answer, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"```\s*\n(.*?)```", answer, re.DOTALL)
    if m:
        return m.group(1)
    return answer


def _run_python(program: str, timeout: float = 15.0) -> tuple:
    """Run a self-contained program in a subprocess. Returns (ok, detail)."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=True) as f:
        f.write(program)
        f.flush()
        try:
            proc = subprocess.run([sys.executable, f.name], capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, {"error": "timeout", "timeout_s": timeout}
        ok = proc.returncode == 0
        detail = {"returncode": proc.returncode}
        if not ok:
            detail["stderr"] = proc.stderr[-2000:]
        return ok, detail


def humaneval_scorer(problem: dict):
    """problem: a HumanEval record with `prompt`, `test`, `entry_point`."""
    prompt = problem["prompt"]
    test = problem["test"]
    entry = problem["entry_point"]

    def score(answer: str) -> tuple:
        code = extract_code(answer)
        # If the model repeated the signature, use its code whole; else append to the prompt.
        body = code if f"def {entry}" in code else prompt + code
        program = f"{body}\n\n{test}\n\ncheck({entry})\n"
        return _run_python(program)

    return score


def mbpp_scorer(problem: dict):
    """problem: an MBPP record with `code`, `test_list`, and optional `test_setup_code`."""
    setup = problem.get("test_setup_code", "")
    tests = "\n".join(problem["test_list"])

    def score(answer: str) -> tuple:
        code = extract_code(answer)
        program = f"{code}\n\n{setup}\n\n{tests}\n"
        return _run_python(program)

    return score


_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _final_number(text: str):
    """The final numeric answer: prefer a value after '####' or 'answer is', else the last
    number in the text. Returns a normalized string or None."""
    m = re.search(r"####\s*(-?\d[\d,]*(?:\.\d+)?)", text or "")
    if not m:
        m = re.search(r"(?i)answer(?:\s+is)?[:\s]+(-?\d[\d,]*(?:\.\d+)?)", text or "")
    if m:
        return m.group(1).replace(",", "")
    nums = _NUM.findall(text or "")
    return nums[-1].replace(",", "") if nums else None


def gsm8k_scorer(problem: dict):
    """problem: a GSM8K record with `answer` ending in '#### <final number>'."""
    gold = _final_number(problem["answer"])

    def score(answer: str) -> tuple:
        pred = _final_number(answer)
        ok = pred is not None and gold is not None and float(pred) == float(gold)
        return ok, {"gold": gold, "pred": pred}

    return score


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def exact_match(gold: str):
    """Scorer: the answer contains the gold string (normalized). For short-answer suites."""
    g = _normalize(gold)

    def score(answer: str) -> tuple:
        ok = g in _normalize(answer)
        return ok, {"gold": gold, "matched": ok}

    return score
