"""
Decisio — Groq LLM Helper

Provides a reusable `get_llm()` factory that returns a ChatGroq
instance configured from environment variables.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

# Default model — fast and capable for structured extraction
_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_DEFAULT_TEMPERATURE = 0.2


def _build_llm(model: str | None, temperature: float | None) -> ChatGroq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY is not set. Add it to your .env file."
        )

    return ChatGroq(
        api_key=api_key,
        model=model or os.getenv("GROQ_MODEL", _DEFAULT_MODEL),
        temperature=temperature if temperature is not None else _DEFAULT_TEMPERATURE,
    )


def get_llm(
    model: str | None = None,
    temperature: float | None = None,
) -> ChatGroq:
    """General-purpose LLM factory used by most agents."""
    return _build_llm(model, temperature)


def get_llm_for_brief(
    model: str | None = None,
    temperature: float | None = None,
) -> ChatGroq:
    """Specialized LLM for Decision Brief generation.

    Currently uses the same defaults as `get_llm`, but split for future tuning.
    """
    return _build_llm(model, temperature)
