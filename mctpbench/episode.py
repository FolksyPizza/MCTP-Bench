"""The `episode` record — one handoff run.

This is the unit of MCTP-Bench data: what was delivered, what the receiver did, and how it
scored. Logged as JSONL so runs accumulate into a training/eval corpus.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class Episode:
    scenario: str
    condition: str          # "flat" | "mctp"
    runner: str             # "mock" | "claude-subagent" | ...
    context_tokens: int     # tokens delivered up front
    packet_node_ids: list   # nodes in the packet (mctp); [] for flat
    retrieved_ids: list     # retrieve-on-demand pulls the receiver made
    retrieved_tokens: int   # tokens pulled on demand
    codebase_reads: int     # fallbacks to raw source NOT in the packet -> severe miss
    used_node_ids: list     # packet nodes the receiver referenced -> USED
    outcome_pass: bool
    criteria: dict          # gold sub-checks -> bool
    misleading: bool        # provided info caused an incorrect claim (MISLEADING label)

    @property
    def total_tokens(self) -> int:
        return self.context_tokens + self.retrieved_tokens

    @property
    def available_unused(self) -> list:
        """Packet nodes with no evidence they mattered -> precision cost."""
        return [n for n in self.packet_node_ids if n not in self.used_node_ids]

    def to_json(self) -> dict:
        d = asdict(self)
        d["total_tokens"] = self.total_tokens
        d["available_unused"] = self.available_unused
        return d


def append_jsonl(path: str, episodes) -> None:
    with open(path, "a") as f:
        for ep in episodes:
            f.write(json.dumps(ep.to_json()) + "\n")


def read_jsonl(path: str) -> list:
    out = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except FileNotFoundError:
        pass
    return out
