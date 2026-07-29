"""
metrics/rag_quality.py — Live RAG answer-quality tracking.

Faithfulness (is the answer grounded in what was retrieved?) is the one
eval/metrics/ RAG metric computable without ground truth, so it's the one
that can run on every live RAG query rather than only in the offline
eval/dataset/*.csv benchmarks. See eval/metrics/_faithfulness_core.py for the
shared scoring formula.

Usage
-----
    from observability.metrics.rag_quality import rag_quality_tracker

    rag_quality_tracker.record(faithfulness=0.82, trace_id="...", question="...")
    summary = rag_quality_tracker.summary()
    # {"count": 1, "avg": 0.82, "p50": 0.82, "p95": 0.82, "recent": [0.82]}
    worst = rag_quality_tracker.worst(5)
    # [{"faithfulness": 0.41, "trace_id": "...", "question": "..."}, ...]
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Optional

_MAX_SAMPLES = 500


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo])


class RagQualityTracker:
    """Thread-safe rolling window of live faithfulness scores."""

    def __init__(self, max_samples: int = _MAX_SAMPLES) -> None:
        self._lock = threading.Lock()
        self._faithfulness: deque[float] = deque(maxlen=max_samples)
        self._records: deque[dict] = deque(maxlen=max_samples)

    def record(self, faithfulness: float, trace_id: Optional[str] = None, question: Optional[str] = None) -> None:
        with self._lock:
            self._faithfulness.append(faithfulness)
            self._records.append({"faithfulness": faithfulness, "trace_id": trace_id, "question": question})

    def summary(self) -> dict[str, Any]:
        with self._lock:
            values = sorted(self._faithfulness)
            recent = list(self._faithfulness)[-20:]

        if not values:
            return {"count": 0, "avg": None, "p50": None, "p95": None, "recent": []}

        return {
            "count": len(values),
            "avg": round(sum(values) / len(values), 3),
            "p50": round(_percentile(values, 50), 3),
            "p95": round(_percentile(values, 95), 3),
            "recent": [round(v, 3) for v in recent],
        }

    def worst(self, n: int = 5) -> list[dict]:
        """The n lowest-scoring recorded queries (trace_id may be None for
        older records that predate trace_id being threaded through)."""
        with self._lock:
            records = list(self._records)
        return sorted(records, key=lambda r: r["faithfulness"])[:n]

    def reset(self) -> None:
        with self._lock:
            self._faithfulness.clear()
            self._records.clear()


# Singleton instance — import and use directly:
#   from observability.metrics.rag_quality import rag_quality_tracker
rag_quality_tracker = RagQualityTracker()
