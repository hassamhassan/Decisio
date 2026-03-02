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


def get_llm(
    model: str | None = None,
    temperature: float | None = None,
) -> ChatGroq:
    """Return a ChatGroq instance.

    Parameters
    ----------
    model : str, optional
        Groq model name.  Falls back to ``GROQ_MODEL`` env var, then
        ``llama-3.3-70b-versatile``.
    temperature : float, optional
        Sampling temperature. Falls back to 0.2.
    """
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
