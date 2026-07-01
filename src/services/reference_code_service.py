"""
Reference code detection and direct lookup for operator code-meaning queries.

Detects uppercase reference codes (e.g. RV-PUMP07-THERMAL-92) and classifies
whether the user is asking for a direct explanation vs. reporting a live incident.
"""

from __future__ import annotations

import re
from typing import Any

# At least two hyphen-separated segments; letters, digits, underscores.
# Matches RV-..., KB-..., SOP-GLOBAL-LOTO-01, etc.
REFERENCE_CODE_PATTERN = re.compile(
    r"\b[A-Z][A-Z0-9_]*(?:-[A-Z0-9][A-Z0-9_-]*)+\b"
)

# Meaning / lookup intent keywords (message must also contain a reference code)
_MEANING_INTENT = re.compile(
    r"\b(?:"
    r"what\s+is|what\s+does|explain|define|meaning|"
    r"require(?:s|ment)?|refer(?:s)?\s+to"
    r")\b",
    re.I,
)

_LIVE_INCIDENT_PATTERNS = (
    re.compile(r"\d+\s*°?\s*c\b", re.I),
    re.compile(r"\bbearing\b.*\b(temp|temperature|hot|overheat)", re.I),
    re.compile(r"\bburning\s+smell\b", re.I),
    re.compile(r"\bwhat\s+should\s+(i|we)\s+do\b", re.I),
    re.compile(r"\btripped\b", re.I),
    re.compile(r"\balarm\b", re.I),
    re.compile(r"\bemergency\b", re.I),
    re.compile(r"\bvibration\b", re.I),
    re.compile(r"\bleak\b", re.I),
    re.compile(r"\bshutdown\s+required\b", re.I),
    re.compile(r"\bcurrently\s+(running|operating|at)\b", re.I),
    re.compile(r"\bis\s+at\s+\d+", re.I),
    re.compile(r"\bhas\s+a\b.*\b(reading|smell|alarm)\b", re.I),
)

# Leading equipment tokens only — not intent words (WHAT, EXPLAIN) or reference codes.
_LEADING_EQUIPMENT_PATTERNS = (
    re.compile(r"^\s*(DUCT\s+AC\d+)\s*(?::|\s+)\s*", re.I),
    re.compile(r"^\s*([A-Z]{2,}-\d+)\s*(?::|\s+)\s*", re.I),
)


def extract_reference_codes(text: str) -> list[str]:
    """Return unique reference codes found in text, preserving first-seen order."""
    if not text:
        return []
    seen: set[str] = set()
    codes: list[str] = []
    for match in REFERENCE_CODE_PATTERN.finditer(text.upper()):
        code = match.group(0).upper()
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _is_bare_code_query(text: str, codes: list[str]) -> bool:
    """True when the message is essentially just a reference code (lookup request)."""
    if not text or not codes:
        return False
    stripped = text.strip().rstrip("?.!").strip()
    if len(codes) == 1 and stripped.upper() == codes[0]:
        return True
    if len(codes) == 1 and REFERENCE_CODE_PATTERN.fullmatch(stripped.upper()):
        return True
    return False


def is_code_meaning_question(text: str) -> bool:
    """True when the message is asking for the meaning of a reference code."""
    if not text:
        return False
    codes = extract_reference_codes(text)
    if not codes:
        return False
    if _is_bare_code_query(text, codes):
        return True
    return bool(_MEANING_INTENT.search(text))


def describes_live_incident(text: str) -> bool:
    """True when the message also describes an active operational incident."""
    if not text:
        return False
    return any(p.search(text) for p in _LIVE_INCIDENT_PATTERNS)


def classify_reference_code_intent(text: str) -> str:
    """
    Classify user intent for reference-code handling.

    Returns:
      - "none" — not a code-meaning query
      - "code_only" — explain code only; skip diagnostic loop
      - "code_with_incident" — explain code then continue diagnosis
    """
    if not is_code_meaning_question(text):
        return "none"
    if describes_live_incident(text):
        return "code_with_incident"
    return "code_only"


def _leading_equipment_id(text: str) -> str:
    """Extract a leading equipment/asset token when explicitly prefixed in user text."""
    if not text:
        return ""
    for pattern in _LEADING_EQUIPMENT_PATTERNS:
        match = pattern.match(text)
        if match:
            return re.sub(r"\s+", " ", match.group(1).strip().upper())
    return ""


def resolve_asset_id(text: str, incident_card: dict[str, Any] | None) -> str:
    """Resolve equipment/asset ID from incident card or leading equipment prefix."""
    ic = incident_card or {}
    asset = (ic.get("asset_id") or "").strip().upper()
    if asset:
        return asset
    return _leading_equipment_id(text or "")


def build_code_lookup_query(text: str, codes: list[str]) -> str:
    """Build retrieval query text prioritizing the reference code(s)."""
    primary = codes[0] if codes else ""
    return f"{primary} {text}".strip()[:500]


def build_not_verified_answer(codes: list[str], asset_id: str) -> str:
    """Deterministic response when no matching reference source is retrieved."""
    code_str = ", ".join(codes) if codes else "the reference code"
    asset_part = f" for {asset_id}" if asset_id else ""
    return (
        f"{code_str} could not be verified from the available references{asset_part}. "
        "No matching source text was retrieved from the scoped reference library. "
        "Please consult an authorized supervisor or maintenance documentation."
    )


def build_grounded_answer_prompt(
    codes: list[str],
    asset_id: str,
    retrieved_chunks: list[dict],
    user_text: str,
) -> str:
    """Build LLM context for a grounded code explanation."""
    parts = [
        "=== USER QUESTION ===",
        user_text,
        "",
        f"=== REFERENCE CODE(S) ===",
        ", ".join(codes),
        f"Asset: {asset_id or 'not specified'}",
    ]
    if retrieved_chunks:
        parts.append("\n=== RETRIEVED REFERENCE EXCERPTS (use ONLY these) ===")
        for i, chunk in enumerate(retrieved_chunks[:6], 1):
            label = chunk.get("title") or chunk.get("source_filename") or f"source-{i}"
            score = chunk.get("score", 0)
            text_excerpt = (chunk.get("text") or "")[:800]
            parts.append(f"[{label}, relevance {score:.0%}] {text_excerpt}")
    else:
        parts.append("\n=== RETRIEVED REFERENCE EXCERPTS ===\n(none above relevance threshold)")
    parts.append(
        "\nExplain what the reference code means using ONLY the excerpts above. "
        "If excerpts do not define the code, state that it could not be verified. "
        "Do not invent thresholds, procedures, or meanings."
    )
    return "\n".join(parts)


CODE_LOOKUP_SYSTEM_PROMPT = """\
You are a reference-code lookup assistant for Decisio.

The operator is asking what a specific reference code means (e.g. RV-PUMP07-THERMAL-92).

Rules:
- Answer using ONLY the retrieved reference excerpts provided.
- Name the code and the asset when known.
- If the excerpts describe thresholds, conditions, or required actions, include them.
- If the excerpts do not define the code, say it could not be verified from available references.
- Do NOT invent meanings, thresholds, or procedures.
- Do NOT start a diagnostic questionnaire.
- Keep the answer to 2-4 sentences unless the excerpts require more detail.
- Do not include repair step-by-step instructions.
"""
