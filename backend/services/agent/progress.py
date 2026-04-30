"""
agent/progress.py — Lightweight per-session progress event registry.

Nodes call emit() with a step key and human-readable label.
The SSE endpoint in api/agent.py registers a queue, streams events to the
frontend, and unregisters when the response is complete.
"""

from __future__ import annotations

import queue
from typing import Optional

# session_id → Queue[dict]
_registry: dict[str, queue.Queue] = {}


def register(session_id: str) -> queue.Queue:
    """Create and store a queue for this session. Returns the queue."""
    q: queue.Queue = queue.Queue()
    _registry[session_id] = q
    return q


def unregister(session_id: str) -> None:
    _registry.pop(session_id, None)


def emit(session_id: str, step: str, label: str) -> None:
    """
    Push a progress event onto the session queue (non-blocking).
    Silently no-ops if the session is not registered (non-streaming request).
    """
    q = _registry.get(session_id)
    if q is not None:
        try:
            q.put_nowait({"type": "progress", "step": step, "label": label})
        except queue.Full:
            pass
