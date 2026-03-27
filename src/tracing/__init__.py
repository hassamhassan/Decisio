"""
Decisio — Tracing / dual_write_trace_context integration.

Emit escalation and operational events for observability.
Replace with real dual_write_trace_context when available.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# In-memory event log for tests; production can replace with dual_write_trace_context
_trace_events: list[dict[str, Any]] = []


def emit_trace(event: str, payload: dict[str, Any] | None = None) -> None:
    """
    Emit a trace event (escalation.created, escalation.message_sent, etc.).
    Integrate with dual_write_trace_context when available.
    """
    payload = payload or {}
    record = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    _trace_events.append(record)
    # Prevent unbounded memory growth in production
    if len(_trace_events) > 1000:
        _trace_events[:] = _trace_events[-500:]
    logger.info("trace: %s %s", event, payload)


def get_trace_events() -> list[dict[str, Any]]:
    """Return collected trace events (for tests)."""
    return list(_trace_events)


def clear_trace_events() -> None:
    """Clear trace events (for tests)."""
    _trace_events.clear()
