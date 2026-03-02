"""
Decisio — Boundary & Execution Safety Sanitization

Programmatic enforcement that Decision Brief outputs never include
execution instructions, step-by-step procedures, setpoints, disassembly,
or operational commands. Used after LLM generation to redact or reject
any content that violates the decision-only boundary.

Safety boundary: §6.8 — decisions only, not how to execute.
"""

from __future__ import annotations

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Forbidden phrases (case-insensitive) that indicate execution instructions ──
# These trigger redaction to preserve human-in-the-loop and decision-only boundary.
FORBIDDEN_PHRASES = [
    r"step\s*\d+",                    # "step 1", "step 2"
    r"setpoint",                      # control setpoints
    r"set\s+the\s+",                  # "set the valve"
    r"turn\s+off",                    # operational command
    r"turn\s+on",
    r"switch\s+off",
    r"switch\s+on",
    r"disassemble",
    r"disassembly",
    r"remove\s+the\s+(?:cover|panel|bolt)",  # disassembly language
    r"tighten\s+the",
    r"loosen\s+the",
    r"open\s+the\s+valve",            # direct valve command
    r"close\s+the\s+valve",
    r"adjust\s+the\s+setpoint",
    r"set\s+to\s+\d+",                # "set to 100"
    r"calibrate\s+to\s+",
    r"replace\s+with\s+part\s+#",     # repair instruction
    r"install\s+the\s+",
    r"reinstall\s+the",
    r"torque\s+to\s+\d+",             # mechanical procedure
    r"first\s+loosen",                # procedure steps
    r"then\s+remove",
    r"command\s+sequence",
    r"operational\s+command",
    r"run\s+the\s+following",
    r"execute\s+the\s+following",
    r"follow\s+these\s+steps",
    r"procedure\s*:\s*1\.",
]

# Compiled for reuse
_FORBIDDEN_PATTERNS = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PHRASES]

# Placeholder for redacted content (decision-level only; no execution)
REDACTED_PLACEHOLDER = "[Description redacted: decision-level only; no execution steps.]"


def _contains_execution_language(text: str) -> bool:
    """Return True if text contains any forbidden execution-language phrase."""
    if not text or not isinstance(text, str):
        return False
    for pat in _FORBIDDEN_PATTERNS:
        if pat.search(text):
            return True
    return False


def _redact_text(text: str) -> str:
    """Replace forbidden phrases with placeholder. Returns redacted string."""
    if not text or not isinstance(text, str):
        return text
    out = text
    for pat in _FORBIDDEN_PATTERNS:
        out = pat.sub(REDACTED_PLACEHOLDER, out)
    # If we redacted anything, collapse repeated placeholders
    while REDACTED_PLACEHOLDER * 2 in out:
        out = out.replace(REDACTED_PLACEHOLDER * 2, REDACTED_PLACEHOLDER)
    return out.strip() or REDACTED_PLACEHOLDER


def sanitize_decision_brief(
    result: dict[str, Any],
    safety_constraints: list[str],
    safety_blocks: list[str],
) -> tuple[dict[str, Any], bool]:
    """
    Scan options[].description and analysis_summary for execution instructions.
    Redact offending text. Do not remove options; only sanitize content.

    Returns:
        (sanitized_result, had_violations): had_violations True if any redaction occurred.
    """
    had_violations = False
    out = dict(result)

    # Sanitize analysis_summary
    summary = out.get("analysis_summary") or ""
    if _contains_execution_language(summary):
        had_violations = True
        out["analysis_summary"] = _redact_text(summary)
        logger.warning("Decision Brief: execution language redacted in analysis_summary")

    # Sanitize each option description
    options = out.get("options") or []
    for i, opt in enumerate(options):
        if not isinstance(opt, dict):
            continue
        desc = opt.get("description") or ""
        if _contains_execution_language(desc):
            had_violations = True
            options[i] = {**opt, "description": _redact_text(desc)}
            logger.warning("Decision Brief: execution language redacted in option %s description", opt.get("option_id", i + 1))
        # Also check title for obvious commands
        title = opt.get("title") or ""
        if _contains_execution_language(title):
            had_violations = True
            options[i] = {**options[i], "title": _redact_text(title)}

    out["options"] = options
    return out, had_violations
