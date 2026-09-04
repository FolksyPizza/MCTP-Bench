"""Swarm adapter — multi-agent pipelines that share ASTP state.

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


# Distractor handoffs that pad a pipeline to its target depth. They do real (if generic) work
# and deliberately do NOT restate the carried design decision, so the decision must survive the
# pipeline through the threaded state alone.
_DISTRACTORS = [
    ("reviewer", "Review the overall approach for {fn} for general code quality.",
     "Give a short bulleted review. Do not restate any specific numeric or formatting decisions."),
    ("documenter", "Draft a one-paragraph module docstring describing what {fn} is for.",
     "Write a single concise paragraph."),
    ("planner", "Outline a high-level testing plan for {fn}.",
     "List the test categories as brief bullet points."),
    ("risk", "Identify the main risks or failure modes when building {fn}.",
     "List the risks as brief bullet points."),
    ("perf", "Comment on the performance characteristics expected of {fn}.",
     "Write one short paragraph."),
    ("integrator", "Describe how {fn} fits into a larger utilities module.",
     "Write one short paragraph."),
]


def _pipeline(task_id: str, brief: str, fn: str, asserts: list, carry: str = "",
              depth: int = 3) -> SwarmTask:
    """A depth-`depth` pipeline. The architect establishes a carried design decision, distractor
    stages pad the depth without restating it, and the final engineer must honor the decision it
    can only have learned through the threaded state. This is the multi-agent test: the earlier a
    decision is set and the more handoffs it must survive, the more the delivery method matters."""
    stages = [
        Stage("architect",
              f"Establish the mandatory design decision for {fn}.",
              f"Output exactly one line and nothing else: DESIGN DECISION: {carry}."),
    ]
    for j in range(max(1, depth - 2)):
        role, instr, recv = _DISTRACTORS[j % len(_DISTRACTORS)]
        stages.append(Stage(role, instr.format(fn=fn), recv.format(fn=fn)))
    stages.append(Stage(
        "engineer",
        f"Implement {fn} in Python. You must honor every DESIGN DECISION established earlier in "
        f"this project, even if it is not repeated here.",
        "Write the complete function inside a single ```python code block. No prose.",
        objective=_asserts_objective(fn, asserts)))
    return SwarmTask(task_id=task_id, brief=brief, stages=stages)


def _data_path() -> str:
    env = os.environ.get("ASTP_SWARM")
    if env and os.path.exists(env):
        return env
    return os.path.join(_HERE, "..", "data", "swarm.jsonl")


# built-in fallback when no generated dataset is present
_BUILTIN = [("swarm/slugify",
             "Add a function slugify(text) that lowercases the text, replaces each run of "
             "non-alphanumeric characters with a single separator, and strips leading and "
             "trailing separators.", "slugify",
             ["assert slugify('Hello World!') == 'hello_world'",
              "assert slugify('  A..B  ') == 'a_b'",
              "assert slugify('already_slug') == 'already_slug'"],
             "the separator character must be '_' (underscore), never a hyphen", 3)]


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
                    specs.append((r["task_id"], r["brief"], r["spec_name"], r["asserts"],
                                  r.get("carry", ""), r.get("depth", 3)))
        else:
            specs = _BUILTIN
        if limit:
            specs = specs[:limit]
        for task_id, brief, fn, asserts, carry, depth in specs:
            yield _pipeline(task_id, brief, fn, asserts, carry, depth)
