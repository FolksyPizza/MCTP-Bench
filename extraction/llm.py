"""LLM-backed extractor — the ceiling.

Prompts a model to read a task and its source and emit an MCTP graph in the closed v0.1
vocabulary: `task`/`artifact`/`entity`/`decision` nodes and the relation set, including
superseded approaches. Node/edge types are validated against the Core vocabulary and anything
off-vocabulary is dropped, so the produced graph is always well-formed even when the model is
not. Artifact node content (source bytes) is taken from the repo snapshot by path, so the model
selects and links files rather than reproducing them.

This extractor's fidelity bounds the whole system (see extraction/__init__.py). It requires the
model server and is not run here; large repositories need chunked extraction, which this skeleton
notes but does not yet implement (it sends the snapshot in one request).
"""
from __future__ import annotations

import json
import re

from mctp import NODE_TYPES, RELATION_TYPES, MCTPStore

from mctpbench.runner import OpenAICompatRunner

from .base import Extractor, language_of, prov

EXTRACT_PROMPT = (
    "Extract a structured state graph from the material below, for handing off to another agent.\n"
    "Emit a single JSON object with keys `nodes`, `edges`, and `supersedes`.\n"
    "- nodes: objects with `id` (short slug), `type` (one of task, artifact, entity, decision), "
    "and `content` (a concise statement). For a file, set type=artifact and add `path` naming "
    "the file; do not copy the file's contents into `content`.\n"
    "- edges: objects with `from`, `to` (node ids) and `relation` (one of calls, depends_on, "
    "modifies, supersedes, contradicts, derived_from, relates_to).\n"
    "- supersedes: objects with `old` and `new` node ids, when a decision replaced an earlier one.\n"
    "Capture decisions and any rejected or superseded approach and the reason. Use the given task "
    "id `{task_id}` for the primary task node. Reply with only the JSON object.\n\n"
    "TASK:\n{task}\n\nSOURCE FILES:\n{files}"
)


def _files_blob(repo: dict, max_chars: int = 12000) -> str:
    out, used = [], 0
    for path, content in repo.items():
        block = f"--- {path} ---\n{content}\n"
        if used + len(block) > max_chars:
            out.append(f"--- {path} --- (omitted; snapshot truncated) ---")
            continue
        out.append(block)
        used += len(block)
    return "\n".join(out)


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {"nodes": [], "edges": [], "supersedes": []}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"nodes": [], "edges": [], "supersedes": []}
    d.setdefault("nodes", [])
    d.setdefault("edges", [])
    d.setdefault("supersedes", [])
    return d


class LLMExtractor(Extractor):
    name = "llm"

    def __init__(self, model="", base_url="http://localhost:8000/v1", api_key="EMPTY",
                 max_tokens=4096):
        self._runner = OpenAICompatRunner(base_url=base_url, model=model, api_key=api_key,
                                          max_tokens=max_tokens, max_retrieve_rounds=0)
        self.model = model or "llm"

    def extract(self, repo: dict, task_text: str, task_id: str = "task_main"):
        prompt = EXTRACT_PROMPT.format(task_id=task_id, task=task_text, files=_files_blob(repo))
        raw = self._runner._chat([{"role": "user", "content": prompt}])
        return self.build(_parse(raw), repo, task_id, task_text)

    def build(self, spec: dict, repo: dict, task_id: str, task_text: str):
        """Materialize a parsed spec into a validated MCTPStore. Off-vocabulary types/relations
        are dropped. Public so a stored extraction can be rebuilt without re-calling the model."""
        s = MCTPStore()
        ts = [0]

        def nxt():
            ts[0] += 1
            return ts[0]

        ids = set()
        # ensure the primary task node exists even if the model forgot it
        seen_task = any(n.get("id") == task_id for n in spec["nodes"])
        if not seen_task:
            s.assert_node(task_id, "task", task_text, prov(self.model, nxt()))
            ids.add(task_id)

        for n in spec["nodes"]:
            nid, ntype = n.get("id"), n.get("type")
            if not nid or ntype not in NODE_TYPES or nid in ids:
                continue
            if ntype == "artifact" and n.get("path") in repo:
                path = n["path"]
                content = repo[path]
                lang = language_of(path)
                from .heuristic import _symbols
                s.assert_artifact(nid, path, content, lang, _symbols(lang, content),
                                  prov(self.model, nxt()), descriptor=n.get("content"))
            else:
                s.assert_node(nid, ntype, n.get("content", ""), prov(self.model, nxt()))
            ids.add(nid)

        for e in spec["edges"]:
            f, t, rel = e.get("from"), e.get("to"), e.get("relation")
            if f in ids and t in ids and rel in RELATION_TYPES:
                s.assert_edge(f, t, rel, prov(self.model, nxt()))

        for sup in spec["supersedes"]:
            old, new = sup.get("old"), sup.get("new")
            if old in ids and new in ids:
                s.supersede(old, new, prov(self.model, nxt()))

        return s, task_id
