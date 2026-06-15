"""
Decisio — OpenAI LLM Helper

Provides a reusable `get_llm()` factory that returns a ChatOpenAI
instance configured from environment variables.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# Default model
_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_TEMPERATURE = 0.2


def _build_llm(model: str | None, temperature: float | None) -> ChatOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set. Add it to your .env file."
        )

    return ChatOpenAI(
        api_key=api_key,
        model=model or os.getenv("OPENAI_MODEL", _DEFAULT_MODEL),
        temperature=temperature if temperature is not None else _DEFAULT_TEMPERATURE,
    )


def get_llm(
    model: str | None = None,
    temperature: float | None = None,
) -> ChatOpenAI:
    """General-purpose LLM factory used by most agents."""
    return _build_llm(model, temperature)


def get_llm_fast(
    temperature: float | None = None,
) -> ChatOpenAI:
    """Smaller, faster model for high-frequency Q&A (interpreter, hypothesis, safety, questions).

    Override with env ``DECISIO_LLM_FAST`` (default ``gpt-4o-mini``).
    """
    fast = os.getenv("DECISIO_LLM_FAST", "gpt-4o-mini")
    return _build_llm(model=fast, temperature=temperature)


def get_llm_for_brief(
    model: str | None = None,
    temperature: float | None = None,
) -> ChatOpenAI:
    """Specialized LLM for Decision Brief generation.

    Currently uses the same defaults as `get_llm`, but split for future tuning.
    """
    return _build_llm(model, temperature)
