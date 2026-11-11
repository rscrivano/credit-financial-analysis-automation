"""LLM access: Portkey (course key) or direct OpenAI, hard usage caps, and a token log.

Token efficiency rules (docs/conversation_log.md): deterministic code does all
math; agents get compact inputs; every run is capped and logged.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .config import REPO_ROOT, load_env

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

DEFAULT_MODEL = "gpt-6-luna"  # the only model allowed on the course Portkey key (assignment brief)
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
TOKEN_LOG = REPO_ROOT / "data" / "logs" / "token_usage.jsonl"

# Per-agent caps: a bug or a hostile filing can't burn the budget.
AGENT_LIMITS = {
    "filing_analyst": {"request_limit": 2, "total_tokens_limit": 12000, "output_tokens": 3000},
    "writer": {"request_limit": 2, "total_tokens_limit": 6000, "output_tokens": 1500},
    "economist": {"request_limit": 2, "total_tokens_limit": 6000, "output_tokens": 1500},
    "mapper": {"request_limit": 2, "total_tokens_limit": 5000, "output_tokens": 1500},
}


class LLMUnavailable(Exception):
    pass


def model_name() -> str:
    load_env()
    return os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL


def get_model():
    """PydanticAI model routed through Portkey if PORTKEY_API_KEY is set, else direct OpenAI."""
    load_env()
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    pk = os.environ.get("PORTKEY_API_KEY", "").strip()
    oa = os.environ.get("OPENAI_API_KEY", "").strip()
    if pk:
        client = AsyncOpenAI(api_key=pk, base_url=os.environ.get("PORTKEY_BASE_URL", PORTKEY_BASE_URL),
                             default_headers={"x-portkey-api-key": pk, "x-portkey-provider": "openai"})
    elif oa:
        client = AsyncOpenAI(api_key=oa)
    else:
        raise LLMUnavailable("No PORTKEY_API_KEY or OPENAI_API_KEY found; AI sections are skipped.")
    return OpenAIChatModel(model_name(), provider=OpenAIProvider(openai_client=client))


def limits(agent: str):
    from pydantic_ai.usage import UsageLimits
    c = AGENT_LIMITS[agent]
    return UsageLimits(request_limit=c["request_limit"], total_tokens_limit=c["total_tokens_limit"])


REASONING_EFFORT = "low"  # reasoning models: hidden reasoning counts as output tokens; low keeps it small


def settings(agent: str) -> dict:
    return {"max_tokens": AGENT_LIMITS[agent]["output_tokens"], "openai_reasoning_effort": REASONING_EFFORT}


def usage_dict(usage) -> dict:
    return {
        "requests": getattr(usage, "requests", 0),
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "cached_input_tokens": getattr(usage, "cache_read_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
    }


def log_usage(agent: str, ticker: str, usage: dict, model: str) -> None:
    TOKEN_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "agent": agent, "ticker": ticker, "model": model, **usage}
    with open(TOKEN_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
