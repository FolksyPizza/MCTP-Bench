"""The extractor interface and shared helpers."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mctpbench  # noqa: E402,F401  (bootstraps MCTP_HOME onto sys.path)

from mctp import MCTPStore, Provenance  # noqa: E402

# extension -> language label for artifact refs
LANGUAGES = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".jsx": "javascript", ".java": "java", ".go": "go", ".rb": "ruby", ".rs": "rust",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp",
    ".php": "php", ".kt": "kotlin", ".scala": "scala", ".swift": "swift", ".sql": "sql",
    ".sh": "bash", ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".md": "markdown",
}


def language_of(path: str) -> str:
    return LANGUAGES.get(os.path.splitext(path)[1].lower(), "text")


def prov(model: str, ts: int, source: str = "extractor", agent: str = "extractor",
         conf: float = 1.0) -> Provenance:
    return Provenance(source=source, agent=agent, model=model, timestamp=ts, confidence=conf)


class Extractor:
    name = "extractor"

    def extract(self, repo: dict, task_text: str, task_id: str = "task_main"):
        """repo: {path -> file content}. Returns (MCTPStore, task_node_id)."""
        raise NotImplementedError
