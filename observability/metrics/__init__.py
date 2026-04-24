"""
observability.metrics — LLM cost tracking and system-performance measurement.

Singletons
----------
    cost_tracker  — records token usage + estimates USD cost per LLM call
    perf          — records wall-clock latencies with P50/P95/P99 reporting
    timed         — decorator to time a sync or async function
"""

from observability.metrics.costs import CostTracker, TokenUsage, cost_tracker
from observability.metrics.sys_perf import PerformanceTracker, perf, timed

__all__ = [
    "CostTracker",
    "TokenUsage",
    "cost_tracker",
    "PerformanceTracker",
    "perf",
    "timed",
]
