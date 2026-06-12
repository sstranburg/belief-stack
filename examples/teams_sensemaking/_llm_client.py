"""Shared OpenAI client setup for the synthetic-themes demo (example-local).

Reads configuration from environment variables:
    OPENAI_API_KEY    - required
    OPENAI_MODEL      - chat model for snippet/expectation generation
                        (default: "gpt-4o-mini")
    OPENAI_EMBED_MODEL - embedding model (default: "text-embedding-3-small")

The fail-fast behavior is intentional: this demo is the LLM-driven path. If
the key isn't set, the demo should error clearly rather than silently degrade
to the mock embedder + empirical generator. The mock + empirical path still
exists in the library and tests; the demo just doesn't take it.

Architectural decision recorded with the example, not the library: the demo
hard-requires LLM access so the reviewer sees the substrate-driven L2
expectation rather than a determinism artifact. The library itself remains
LLM-agnostic.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache


DEFAULT_CHAT_MODEL  = "gpt-4o-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"


def require_openai_key() -> str:
    """Return the API key, or exit with a clear error if missing."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print(
            "ERROR: OPENAI_API_KEY is not set.\n"
            "\n"
            "The synthetic-themes demo uses LLM-generated data and an LLM-based\n"
            "L2 expectation generator. Both require an OpenAI API key.\n"
            "\n"
            "Set it and re-run, e.g.:\n"
            "    export OPENAI_API_KEY=sk-...\n"
            "    python examples/synthetic_themes/run_demo.py\n"
            "\n"
            "If you want the deterministic (mock-embedder + empirical-generator)\n"
            "path, see the library tests under tests/ — the demo deliberately\n"
            "does not take that path.\n",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return key


def chat_model() -> str:
    return os.environ.get("OPENAI_MODEL") or DEFAULT_CHAT_MODEL


def embed_model() -> str:
    return os.environ.get("OPENAI_EMBED_MODEL") or DEFAULT_EMBED_MODEL


@lru_cache(maxsize=1)
def get_client():
    """Return a cached OpenAI client. Raises ImportError if `openai` missing."""
    try:
        from openai import OpenAI
    except ImportError as e:
        print(
            "ERROR: the `openai` package is not installed.\n"
            "Install with: pip install -e \".[openai]\"\n",
            file=sys.stderr,
        )
        raise SystemExit(2) from e
    return OpenAI(api_key=require_openai_key())
