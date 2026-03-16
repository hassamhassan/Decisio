"""
Decisio — Input sanitization utilities.

Defends against prompt injection, XSS, and oversized payloads.
"""

from __future__ import annotations

import re
import html

# Max lengths for text fields sent to LLM prompts
MAX_REPORT_LENGTH = 10_000
MAX_ANSWER_LENGTH = 5_000
MAX_CHAT_MESSAGE_LENGTH = 16_000

# Patterns commonly used in prompt injection attacks
_PROMPT_INJECTION_PATTERNS = re.compile(
    r"(?i)"
    r"(ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?))"
    r"|(you\s+are\s+now\s+(a|an|DAN))"
    r"|(system\s*:\s*)"
    r"|(```\s*(system|assistant)\b)"
    r"|(STOP\s+BEING\s+)"
    r"|(do\s+not\s+follow\s+(your|the)\s+(original|system))"
    r"|(\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>)"  # common LLM control tokens
)


def sanitize_user_input(text: str, *, max_length: int = MAX_REPORT_LENGTH) -> str:
    """
    Sanitize user-provided text before passing to LLM or storing.

    1. Truncates to max_length
    2. Strips null bytes and control characters (keeps newlines/tabs)
    3. HTML-escapes angle brackets to prevent XSS in stored content
    4. Flags potential prompt injection patterns with warning markers
    """
    if not text:
        return ""

    # Truncate
    text = text[:max_length]

    # Strip null bytes and non-printable control chars (keep \n \r \t)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # HTML-escape to prevent stored XSS
    text = html.escape(text, quote=False)

    return text


def has_prompt_injection(text: str) -> bool:
    """Check if text contains common prompt injection patterns."""
    return bool(_PROMPT_INJECTION_PATTERNS.search(text))


def wrap_user_content(text: str, label: str = "USER INPUT") -> str:
    """
    Wrap user-provided text in clear delimiters to help the LLM
    distinguish user content from system instructions.

    This is a defense-in-depth measure against prompt injection.
    """
    return (
        f"<{label}>\n"
        f"{text}\n"
        f"</{label}>"
    )
