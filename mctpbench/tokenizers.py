"""Token counting under multiple tokenizers.

The heuristic (approximately four characters per token) is always available and requires no
dependencies. Real tokenizers are used when their libraries are importable:

- `tiktoken:<encoding>` uses OpenAI's tiktoken (e.g. o200k_base for GPT-4o-class models,
  cl100k_base for GPT-3.5/4, gpt2 for the GPT-2 encoding).
- `hf:<model>` uses a Hugging Face tokenizer via transformers, if installed and the model's
  tokenizer files are available locally. This supports open-model families (Qwen, Llama,
  etc.) but is optional and not required to run the benchmark.

tiktoken is installed into the repository virtualenv (`.venv`); run the harness with
`.venv/bin/python` to use it. Under the system interpreter only the heuristic is available.
"""
from __future__ import annotations

import functools
import os

HEURISTIC = "heuristic"
_TIKTOKEN_ENCODINGS = ("gpt2", "cl100k_base", "o200k_base")
# Open-model tokenizers to include as reference counts, when transformers + the tokenizer files
# are available. Override with MCTP_HF_TOKENIZERS (comma-separated model ids). These make token
# amounts comparable under the families actually being run (Qwen, Llama, ...), not only OpenAI's.
_DEFAULT_HF = ("Qwen/Qwen2.5-7B", "meta-llama/Llama-3.1-8B")


def _heuristic(text: str) -> int:
    return max(1, len(text) // 4)


@functools.lru_cache(maxsize=None)
def _tiktoken(encoding: str):
    import tiktoken
    return tiktoken.get_encoding(encoding)


@functools.lru_cache(maxsize=None)
def _hf(model: str):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(model)


def _configured_hf() -> list:
    """`hf:<model>` names from MCTP_HF_TOKENIZERS, or the defaults, if transformers is importable.
    Names are listed optimistically; a model whose files are absent fails lazily at count time and
    is skipped there (see records.ref_token_counts)."""
    try:
        import transformers  # noqa: F401
    except Exception:
        return []
    env = os.environ.get("MCTP_HF_TOKENIZERS")
    models = [m.strip() for m in env.split(",")] if env else list(_DEFAULT_HF)
    return [f"hf:{m}" for m in models if m]


def available() -> list:
    """Names of tokenizers usable in this environment, heuristic first."""
    names = [HEURISTIC]
    try:
        import tiktoken  # noqa: F401
        names += [f"tiktoken:{e}" for e in _TIKTOKEN_ENCODINGS]
    except Exception:
        pass
    names += _configured_hf()
    return names


def reference_set() -> list:
    """Tokenizers used for per-run reference counts. Configurable with MCTP_REF_TOKENIZERS (an
    explicit comma-separated list, overriding everything) or MCTP_HF_TOKENIZERS (open-model
    tokenizers added to the tiktoken encodings). Falls back to the heuristic if nothing else is
    available."""
    env = os.environ.get("MCTP_REF_TOKENIZERS")
    if env:
        return [t.strip() for t in env.split(",") if t.strip()]
    out = []
    try:
        import tiktoken  # noqa: F401
        out += [f"tiktoken:{e}" for e in _TIKTOKEN_ENCODINGS]
    except Exception:
        pass
    out += _configured_hf()
    return out or [HEURISTIC]


def default() -> str:
    """Prefer a real tokenizer when present; fall back to the heuristic."""
    a = available()
    return "tiktoken:o200k_base" if "tiktoken:o200k_base" in a else HEURISTIC


def count(text: str, tokenizer: str = HEURISTIC) -> int:
    if tokenizer == HEURISTIC:
        return _heuristic(text)
    if tokenizer.startswith("tiktoken:"):
        # disallowed_special=() treats any special-token text as ordinary characters.
        return len(_tiktoken(tokenizer.split(":", 1)[1]).encode(text, disallowed_special=()))
    if tokenizer.startswith("hf:"):
        return len(_hf(tokenizer.split(":", 1)[1]).encode(text))
    raise ValueError(f"unknown tokenizer: {tokenizer}")
