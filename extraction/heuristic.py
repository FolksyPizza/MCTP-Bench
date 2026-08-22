"""Deterministic extractor — the reproducible floor.

Turns a repository snapshot into a Core MCTP graph with no model: each file becomes an artifact
node (path, content hash, language, parsed symbols); import statements become `depends_on` edges
between artifacts; the task node is linked (`relates_to`) to the files it names, or, failing an
explicit mention, to the files whose symbols the task references. It extracts structure, not
semantics — it produces no `decision` or `entity` nodes and cannot recover superseded approaches
— so it is a baseline against which the LLM extractor's added fidelity is measured.
"""
from __future__ import annotations

import os
import re

from mctp import MCTPStore

from .base import Extractor, language_of, prov

# Per-language symbol patterns (definition sites only).
_SYMBOLS = {
    "python": [re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", re.M),
               re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.M)],
    "javascript": [re.compile(r"\bfunction\s+([A-Za-z_]\w*)"),
                   re.compile(r"\bclass\s+([A-Za-z_]\w*)"),
                   re.compile(r"\b(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?\(")],
    "java": [re.compile(r"\b(?:class|interface|enum)\s+([A-Za-z_]\w*)"),
             re.compile(r"\b(?:public|private|protected|static|final|\s)+"
                        r"[\w<>\[\],\s]+\s+([A-Za-z_]\w*)\s*\(")],
    "go": [re.compile(r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"),
           re.compile(r"\btype\s+([A-Za-z_]\w*)\s+(?:struct|interface)")],
}
_SYMBOLS["typescript"] = _SYMBOLS["javascript"]

_PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)
_JS_IMPORT = re.compile(r"""(?:import[^'"]*from\s*|require\(\s*)['"]([^'"]+)['"]""")


def _symbols(language: str, content: str, cap: int = 40) -> list:
    out, seen = [], set()
    for pat in _SYMBOLS.get(language, []):
        for m in pat.finditer(content):
            name = m.group(1)
            if name and name not in seen:
                seen.add(name)
                out.append(name)
                if len(out) >= cap:
                    return out
    return out


def _art_id(path: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_").lower()
    return f"art_{slug}"


def _py_module_index(paths: list) -> dict:
    """Map python module dotted-paths to file paths, for import resolution."""
    idx = {}
    for p in paths:
        if not p.endswith(".py"):
            continue
        mod = p[:-3].replace("/", ".")
        idx[mod] = p
        if mod.endswith(".__init__"):
            idx[mod[: -len(".__init__")]] = p
    return idx


def _resolve_js(importer: str, target: str, paths: set) -> str | None:
    if not target.startswith("."):
        return None  # package import, not a repo file
    base = os.path.normpath(os.path.join(os.path.dirname(importer), target))
    for cand in (base, base + ".js", base + ".ts", base + "/index.js", base + "/index.ts"):
        if cand in paths:
            return cand
    return None


class HeuristicExtractor(Extractor):
    name = "heuristic"

    def extract(self, repo: dict, task_text: str, task_id: str = "task_main"):
        s = MCTPStore()
        ts = [0]

        def nxt():
            ts[0] += 1
            return ts[0]

        s.assert_node(task_id, "task", task_text, prov(self.name, nxt()))

        paths = list(repo)
        path_set = set(paths)
        py_index = _py_module_index(paths)
        art_of = {}

        for path in paths:
            content = repo[path]
            lang = language_of(path)
            aid = _art_id(path)
            art_of[path] = aid
            s.assert_artifact(aid, path, content, lang, _symbols(lang, content),
                              prov(self.name, nxt()))

        # dependency edges from imports
        for path in paths:
            content, lang = repo[path], language_of(path)
            targets = set()
            if lang == "python":
                for a, b in _PY_IMPORT.findall(content):
                    mod = a or b
                    hit = py_index.get(mod)
                    if not hit:  # try trimming to the longest known prefix
                        parts = mod.split(".")
                        while parts and not hit:
                            parts.pop()
                            hit = py_index.get(".".join(parts))
                    if hit and hit != path:
                        targets.add(hit)
            elif lang in ("javascript", "typescript"):
                for tgt in _JS_IMPORT.findall(content):
                    hit = _resolve_js(path, tgt, path_set)
                    if hit and hit != path:
                        targets.add(hit)
            for tgt in targets:
                s.assert_edge(art_of[path], art_of[tgt], "depends_on", prov(self.name, nxt()))

        # link the task to the files it names (by basename or symbol), else to all files
        named = _task_links(task_text, repo, art_of)
        for aid in (named or list(art_of.values())):
            s.assert_edge(task_id, aid, "relates_to", prov(self.name, nxt()))

        return s, task_id


def _task_links(task_text: str, repo: dict, art_of: dict) -> list:
    """Artifact ids the task explicitly references (basename or a defined symbol appears)."""
    text = task_text or ""
    hits = []
    for path, aid in art_of.items():
        base = os.path.basename(path)
        if base and base in text:
            hits.append(aid)
            continue
        syms = _symbols(language_of(path), repo[path], cap=20)
        if any(re.search(rf"\b{re.escape(sym)}\b", text) for sym in syms if len(sym) > 2):
            hits.append(aid)
    return hits
