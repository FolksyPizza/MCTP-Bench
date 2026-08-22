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

import os
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scoring.objective import _run_python, extract_code  # noqa: E402


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


def _slugify_objective():
    def score(answer: str) -> tuple:
        code = extract_code(answer)
        program = (code + "\n"
                   "assert slugify('Hello World!') == 'hello-world'\n"
                   "assert slugify('  A..B  ') == 'a-b'\n"
                   "assert slugify('already-slug') == 'already-slug'\n")
        return _run_python(program)
    return score


def _slugify_pipeline() -> SwarmTask:
    brief = ("Add a function slugify(text) to the utils module: lowercase the text, replace each "
             "run of non-alphanumeric characters with a single hyphen, and strip leading and "
             "trailing hyphens.")
    return SwarmTask(
        task_id="swarm/slugify",
        brief=brief,
        stages=[
            Stage("researcher",
                  "Specify the exact behavior of slugify, including edge cases (empty string, "
                  "punctuation runs, leading/trailing symbols, already-slugified input).",
                  "List the required behavior and edge cases as concise bullet points."),
            Stage("engineer",
                  "Implement slugify(text) in Python according to the specification.",
                  "Write the complete function inside a single ```python code block. No prose.",
                  objective=_slugify_objective()),
            Stage("tester",
                  "Write unit tests for slugify that cover the specified edge cases.",
                  "Write the tests as Python assert statements inside a ```python code block."),
        ],
    )


class SwarmAdapter:
    name = "swarm"
    tier = "subagent"
    default_conditions = ("transcript", "summary", "rag", "mctp")

    def tasks(self, limit: int | None = None):
        tasks = [_slugify_pipeline()]
        return tasks[:limit] if limit else tasks
