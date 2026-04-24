"""
observability — structured tracing, audit logging, and metrics for the Decision System.

Quick-start
-----------
    from observability import audit, cost_tracker, perf

    audit.query("show top 10 sales", table="gold.sales", model="gemini-2.5-flash")
    cost_tracker.record("gemini-2.5-flash", input_tokens=800, output_tokens=120)
    with perf.measure("text2sql.query"):
        ...
"""

from observability.audit_logger import audit
from observability.metrics.costs import cost_tracker
from observability.metrics.sys_perf import perf, timed

__all__ = ["audit", "cost_tracker", "perf", "timed"]
