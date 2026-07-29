"""
agent/progress.py — Lightweight per-trace progress event registry.

Nodes call emit() with a step key and human-readable label.
The SSE endpoint in api/agent.py registers a queue, streams events to the
frontend, and unregisters when the response is complete. Every emit() is
also persisted as a span in observability/trace_log.py so the same events
back the /traces waterfall view, not just the live SSE progress bar.
"""

from __future__ import annotations

import queue

try:
    from observability.trace_log import trace_span as _trace_span
except Exception:
    _trace_span = None

# trace_id → Queue[dict]
_registry: dict[str, queue.Queue] = {}


def register(trace_id: str) -> queue.Queue:
    """Create and store a queue for this trace. Returns the queue."""
    q: queue.Queue = queue.Queue()
    _registry[trace_id] = q
    return q


def unregister(trace_id: str) -> None:
    _registry.pop(trace_id, None)


def emit(trace_id: str, step: str, label: str) -> None:
    """
    Push a progress event onto the trace's SSE queue (non-blocking) and
    persist it as a span. Silently no-ops the SSE part if the trace is not
    registered (non-streaming request) — the span is still persisted.
    """
    q = _registry.get(trace_id)
    if q is not None:
        try:
            q.put_nowait({"type": "progress", "step": step, "label": label})
        except queue.Full:
            pass
    if _trace_span is not None:
        _trace_span(trace_id, step, label)
