"""
Bounded sections for LLM prompts.

Long diagnostic runs accumulate large qa_history and retrieved_patterns;
sending the full lists every turn grows tokens, latency, and cost roughly
linearly. We keep the full structures in graph state — only prompts are capped.
"""

from __future__ import annotations


def get_language_instruction(language: str | None) -> str:
    """Return an LLM prompt suffix that forces the response language.

    When the user has selected Arabic in the UI, every user-facing text field
    produced by the LLM (questions, summaries, options, guidance, etc.) must
    be in Arabic.  Internal-only fields (rationale, category keys) stay in
    English so downstream code can parse them reliably.
    """
    if language and language.lower().startswith("ar"):
        return (
            "\n\nIMPORTANT — LANGUAGE: The user's interface is set to Arabic. "
            "You MUST write ALL user-facing text (questions, descriptions, "
            "summaries, titles, guidance, next_message, risk descriptions, etc.) "
            "in Arabic (العربية). Keep JSON keys, category identifiers, and "
            "internal-only fields (like 'rationale') in English."
        )
    return ""



def format_qa_history_for_llm(
    qa_history: list[dict],
    *,
    max_exchanges: int = 8,
    heading: str = "Q&A HISTORY",
    mode: str = "plain",
) -> str:
    """
    Format a bounded tail of qa_history for an LLM prompt.

    mode:
      - "plain": Q: / A: pairs (hypothesis update, simple traces)
      - "question_gen": numbered Q{i} [Step n] with USER_INPUT-wrapped answers
      - "escalation": [Step n] Q/A lines plus optional signals (expert handoff)
    """
    if not qa_history:
        return ""

    n = len(qa_history)
    tail = qa_history[-max_exchanges:] if max_exchanges > 0 else []
    if not tail:
        return ""

    lines = [f"=== {heading} ==="]
    omitted = n - len(tail)
    if omitted > 0:
        lines.append(
            f"(Omitted {omitted} earlier exchange(s); facts and hypotheses summarize prior context.)"
        )

    first_idx = n - len(tail) + 1

    for j, qa in enumerate(tail):
        i = first_idx + j
        q = str(qa.get("question", ""))
        a = str(qa.get("answer", ""))
        step = qa.get("diagnostic_step", "?")

        if mode == "question_gen":
            step_part = f" [Step {step}]" if step not in (None, "", "?") else ""
            lines.append(f"Q{i}{step_part}: {q}")
            lines.append(f"A{i}: <USER_INPUT>{a}</USER_INPUT>")
        elif mode == "escalation":
            lines.append(f"[Step {step}] Q: {q}")
            lines.append(f"         A: {a}")
            sigs = qa.get("signals")
            if sigs:
                lines.append(f"         Signals: {', '.join(str(s) for s in sigs)}")
        else:
            lines.append(f"Q: {q}\nA: {a}")

    return "\n".join(lines)


def format_retrieved_patterns_for_llm(
    patterns: list[dict],
    *,
    max_patterns: int = 4,
    heading: str = "SIMILAR PAST INCIDENTS",
) -> str:
    """Include top-N patterns with truncated text; omit rest with a note."""
    if not patterns:
        return ""

    n = len(patterns)
    cap = max_patterns if max_patterns > 0 else n
    shown = patterns[:cap]
    lines = [f"=== {heading} ==="]
    if n > cap:
        lines.append(f"(Showing top {cap} of {n} retrieved patterns by relevance.)")

    for p in shown:
        title = str(p.get("title", ""))
        decision =str(p.get("decision_taken", ""))
        score = p.get("similarity_score", 0) or 0
        try:
            pct = float(score)
        except (TypeError, ValueError):
            pct = 0.0
        lines.append(f"- {title} (similarity: {pct:.0%}) → {decision}")

    return "\n".join(lines)


def format_fact_line(
    f: object,
    *,
    escalation: bool = False,
    confidence: bool | str = False,
) -> str:
    """Format one fact for LLM prompts. Tolerates legacy non-dict facts (e.g. bare strings)."""
    if not isinstance(f, dict):
        return f"- {f!s}"
    line = f"- {f.get('key', '?')}: {f.get('value', '?')}"
    if escalation and f.get("contradiction"):
        line += " ⚠️ CONTRADICTION"
    if confidence is True:
        try:
            c = float(f.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            c = 0.0
        line += f" (confidence: {c:.0%})"
    elif confidence == "raw":
        line += f" (confidence: {f.get('confidence', 0)})"
    return line


def fact_value_only(f: object) -> str:
    """Extract display value from a fact for summaries / key_findings lists."""
    if isinstance(f, dict):
        return str(f.get("value", "") or "")
    return str(f or "")
