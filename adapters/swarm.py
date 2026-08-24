"""Swarm adapter — multi-agent pipelines that share MCTP state.

Each swarm task is a `brief` plus an ordered list of `Stage`s. The stages are run by the
multi-handoff pipeline (`mctpbench/pipeline.py`), which threads the accumulating state through
each condition. This adapter yields `SwarmTask`s (not the flat `Task`s the matrix runner uses),
so `run_benchmark.py` dispatches the `swarm` suite to the pipeline path.

The bundled example is a research -> implementation -> testing pipeline for a small utility. The
implementation stage has an objective scorer (the produced function is executed against a couple
of assertions); the research and testing stages are judged.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scoring.objective import _run_python, extract_code  # noqa: E402

_HERE = os.path.dirname(__file__)


@dataclass
class Stage:
    role: str
    instruction: str                 # the stage's task (the receiver's TASK)
    receiver_instruction: str        # how the stage should respond
    objective: Optional[Callable] = None


@dataclass
class SwarmTask:
    task_id: str
    brief: str
    stages: list = field(default_factory=list)


def _asserts_objective(fn: str, asserts: list):
    """Engineer-stage scorer: run the produced function against the spec's assert statements."""
    def score(answer: str) -> tuple:
        code = extract_code(answer)
        program = code + "\n" + "\n".join(asserts) + "\n"
        return _run_python(program)
    return score


def _pipeline(task_id: str, brief: str, fn: str, asserts: list) -> SwarmTask:
    """A research -> implementation -> testing pipeline for one small utility spec."""
    return SwarmTask(
        task_id=task_id, brief=brief,
        stages=[
            Stage("researcher",
                  f"Specify the exact behavior of {fn}, including edge cases (empty input, "
                  f"boundary sizes, already-satisfying input).",
                  "List the required behavior and edge cases as concise bullet points."),
            Stage("engineer",
                  f"Implement {fn} in Python according to the specification.",
                  "Write the complete function inside a single ```python code block. No prose.",
                  objective=_asserts_objective(fn, asserts)),
            Stage("tester",
                  f"Write unit tests for {fn} that cover the specified edge cases.",
                  "Write the tests as Python assert statements inside a ```python code block."),
        ],
    )


def _data_path() -> str:
    env = os.environ.get("MCTP_SWARM")
    if env and os.path.exists(env):
        return env
    return os.path.join(_HERE, "..", "data", "swarm.jsonl")


# built-in fallback when no generated dataset is present
_BUILTIN = [("swarm/slugify",
             "Add a function slugify(text): lowercase the text, replace each run of "
             "non-alphanumeric characters with a single hyphen, and strip leading/trailing "
             "hyphens.", "slugify",
             ["assert slugify('Hello World!') == 'hello-world'",
              "assert slugify('  A..B  ') == 'a-b'",
              "assert slugify('already-slug') == 'already-slug'"])]


class SwarmAdapter:
    name = "swarm"
    tier = "subagent"
    default_conditions = ("transcript", "summary", "rag", "mctp")

    def tasks(self, limit: int | None = None):
        path = _data_path()
        specs = []
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    r = json.loads(line)
                    specs.append((r["task_id"], r["brief"], r["spec_name"], r["asserts"]))
        else:
            specs = _BUILTIN
        if limit:
            specs = specs[:limit]
        for task_id, brief, fn, asserts in specs:
            yield _pipeline(task_id, brief, fn, asserts)
