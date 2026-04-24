"""
metrics/sys_perf.py — Latency and system-performance tracking.

Provides a context manager and a decorator for timing any code block,
plus a session-level accumulator so you can report P50/P95/P99 latencies
per operation in health-check or metrics endpoints.

Usage
-----
    from observability.metrics.sys_perf import perf, timed

    # Context manager
    with perf.measure("text2sql.query"):
        result = data_service.execute_query(sql)

    # Decorator
    @timed("rag.retrieval")
    def retrieve(query: str) -> list:
        ...

    # Read stats
    stats = perf.stats("text2sql.query")
    # {"operation": "text2sql.query", "count": 12, "mean_ms": 340.2,
    #  "p50_ms": 310.0, "p95_ms": 820.1, "p99_ms": 1240.3,
    #  "min_ms": 95.0, "max_ms": 1450.0}

    all_stats = perf.all_stats()
    perf.reset()
"""

from __future__ import annotations

import asyncio
import functools
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncGenerator, Callable, Generator, Optional


# ---------------------------------------------------------------------------
# Percentile helper (no numpy dependency)
# ---------------------------------------------------------------------------

def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo])


# ---------------------------------------------------------------------------
# PerformanceTracker
# ---------------------------------------------------------------------------

class PerformanceTracker:
    """Thread-safe latency recorder keyed by operation name."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, list[float]] = {}  # operation → [ms, ...]

    # -- Recording ------------------------------------------------------------

    def record(self, operation: str, duration_ms: float) -> None:
        """Add a single latency observation (milliseconds)."""
        with self._lock:
            if operation not in self._data:
                self._data[operation] = []
            self._data[operation].append(duration_ms)

    @contextmanager
    def measure(self, operation: str) -> Generator[None, None, None]:
        """Context manager that records wall-clock time for a sync block."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record(operation, elapsed_ms)

    @asynccontextmanager
    async def ameasure(self, operation: str) -> AsyncGenerator[None, None]:
        """Async context manager that records wall-clock time for an async block."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record(operation, elapsed_ms)

    # -- Stats ----------------------------------------------------------------

    def stats(self, operation: str) -> dict[str, Any]:
        """Return latency statistics for a single operation."""
        with self._lock:
            values = sorted(self._data.get(operation, []))

        if not values:
            return {"operation": operation, "count": 0}

        return {
            "operation": operation,
            "count": len(values),
            "mean_ms": round(sum(values) / len(values), 2),
            "min_ms": round(values[0], 2),
            "max_ms": round(values[-1], 2),
            "p50_ms": round(_percentile(values, 50), 2),
            "p95_ms": round(_percentile(values, 95), 2),
            "p99_ms": round(_percentile(values, 99), 2),
        }

    def all_stats(self) -> list[dict[str, Any]]:
        """Return latency statistics for every recorded operation."""
        with self._lock:
            operations = list(self._data.keys())
        return [self.stats(op) for op in sorted(operations)]

    def last_ms(self, operation: str) -> Optional[float]:
        """Return the most recent recorded latency for an operation, or None."""
        with self._lock:
            values = self._data.get(operation)
        return values[-1] if values else None

    def reset(self, operation: Optional[str] = None) -> None:
        """Clear recorded data.  Pass operation= to reset only one key."""
        with self._lock:
            if operation is None:
                self._data.clear()
            else:
                self._data.pop(operation, None)


# ---------------------------------------------------------------------------
# Decorator helper
# ---------------------------------------------------------------------------

def timed(operation: str, tracker: Optional[PerformanceTracker] = None) -> Callable:
    """
    Decorator that measures and records the wall-clock duration of a function.
    Works for both sync and async functions.

        @timed("rag.retrieval")
        def retrieve(query: str) -> list: ...

        @timed("text2sql.query")
        async def query_endpoint(...): ...

    Uses the module-level `perf` singleton by default; pass tracker= to use a
    different instance (useful in tests).
    """
    def decorator(fn: Callable) -> Callable:
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                _tracker = tracker or perf
                async with _tracker.ameasure(operation):
                    return await fn(*args, **kwargs)
            return async_wrapper
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                _tracker = tracker or perf
                with _tracker.measure(operation):
                    return fn(*args, **kwargs)
            return sync_wrapper
    return decorator


# Singleton instance — import and use directly:
#   from observability.metrics.sys_perf import perf, timed
perf = PerformanceTracker()
