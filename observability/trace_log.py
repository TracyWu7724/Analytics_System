"""
trace_log.py — In-house, LangSmith-style span logging for the LangGraph agent.

Every agent run gets a trace_id. Nodes call progress.emit(trace_id, step,
label) as they start each unit of work (routing, generating SQL, retrieving
chunks, etc); progress.emit() forwards here to append a structured JSONL
record to observability/logs/traces.log. trace_start/trace_end bookend the
run so a reader can turn the sequence of point-in-time span markers into a
waterfall of durations — each span's duration is simply the time until the
next span (or trace end) begins, since this pipeline executes its steps
sequentially rather than concurrently.

This is deliberately not the LangSmith SDK (see observability/tracing.py,
an unused pre-LangGraph-refactor module that wraps calls with @traceable and
needs a LangSmith API key) — same idea (a run tree of named, timed spans),
no external service, consistent with this project's audit_logger.py.

Usage
-----
    from observability.trace_log import trace_start, trace_span, trace_end

    trace_start(trace_id, question)
    ...
    trace_span(trace_id, "generating", "Generating SQL...")
    ...
    trace_end(trace_id, route="sql", latency_ms=1234.5)
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

_TRACE_LOG_PATH = Path(__file__).resolve().parent / "logs" / "traces.log"
_lock = threading.Lock()


def _write(record: dict) -> None:
    try:
        _TRACE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with open(_TRACE_LOG_PATH, "a") as f:
                f.write(json.dumps(record) + "\n")
    except Exception:
        pass


def trace_start(trace_id: str, question: str, llm_model: Optional[str] = None) -> None:
    if not trace_id:
        return
    _write({
        "event": "trace.start",
        "trace_id": trace_id,
        "ts": time.time(),
        "question": question,
        "llm_model": llm_model,
    })


def trace_span(trace_id: str, step: str, label: str) -> None:
    if not trace_id:
        return
    _write({"event": "trace.span", "trace_id": trace_id, "ts": time.time(), "step": step, "label": label})


def trace_end(
    trace_id: str,
    route: Optional[str],
    latency_ms: float,
    error: Optional[str] = None,
    final_answer: Optional[str] = None,
    sql_query: Optional[str] = None,
    sql_table: Optional[str] = None,
    mdl_metrics_referenced: Optional[list] = None,
    entity_resolutions: Optional[list] = None,
) -> None:
    if not trace_id:
        return
    _write({
        "event": "trace.end",
        "trace_id": trace_id,
        "ts": time.time(),
        "route": route,
        "latency_ms": latency_ms,
        "error": error,
        "final_answer": final_answer,
        "sql_query": sql_query,
        "sql_table": sql_table,
        "mdl_metrics_referenced": mdl_metrics_referenced,
        "entity_resolutions": entity_resolutions,
    })
