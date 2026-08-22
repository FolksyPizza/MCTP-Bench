"""A dependency-free lexical retriever for the `rag` condition.

TF-IDF cosine over whitespace/punctuation-split tokens, implemented in pure Python so the
benchmark needs no embedding model or vector store. This is deliberately a conventional,
easily reproduced RAG baseline; a dense-embedding variant can be added later as a separate
retriever without changing the condition interface. Retrieval cost is reported as the tokens
of the chunks actually placed in context (embedding/query inference for a dense variant would
be counted as `prep_tokens`).
"""
from __future__ import annotations

import math
import re
from collections import Counter

_WORD = re.compile(r"[A-Za-z0-9_]+")


def _tok(text: str) -> list:
    return _WORD.findall(text.lower())


def chunk(text: str, size: int = 60, overlap: int = 10) -> list:
    """Split text into overlapping word-count chunks. Returns list[str]."""
    words = text.split()
    if not words:
        return []
    step = max(1, size - overlap)
    return [" ".join(words[i:i + size]) for i in range(0, len(words), step)]


class TfidfRetriever:
    def __init__(self, docs: list):
        """docs: list[str] chunks."""
        self.docs = docs
        self.tf = [Counter(_tok(d)) for d in docs]
        df = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = max(1, len(docs))
        self.idf = {w: math.log((1 + n) / (1 + df[w])) + 1.0 for w in df}
        self.norms = [self._norm(c) for c in self.tf]

    def _norm(self, counts: Counter) -> float:
        return math.sqrt(sum((v * self.idf.get(w, 0.0)) ** 2 for w, v in counts.items())) or 1.0

    def search(self, query: str, k: int = 4) -> list:
        """Return the top-k (index, score) chunks by TF-IDF cosine similarity."""
        q = Counter(_tok(query))
        qnorm = self._norm(q)
        scored = []
        for i, counts in enumerate(self.tf):
            dot = sum(q.get(w, 0) * v * self.idf.get(w, 0.0) ** 2
                      for w, v in counts.items())
            scored.append((i, dot / (qnorm * self.norms[i])))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(i, s) for i, s in scored[:k] if s > 0]
