"""
metrics/costs.py — LLM token-usage tracking and cost estimation.

Records token counts per call and accumulates session totals.  Pricing
tables are based on publicly published rates (USD per 1 M tokens) and are
easy to update when providers change their rates.

Usage
-----
    from observability.metrics.costs import cost_tracker

    # After an LLM call that returned usage info:
    cost_tracker.record(
        model="gemini-2.5-flash",
        input_tokens=1200,
        output_tokens=350,
    )

    summary = cost_tracker.summary()
    # {"total_input_tokens": 1200, "total_output_tokens": 350,
    #  "total_cost_usd": 0.000255, "calls": 1, "by_model": {...}}

    cost_tracker.reset()   # clear session totals
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Pricing table  (USD per 1 M tokens, as of 2025-04)
# ---------------------------------------------------------------------------

# fmt: off
_PRICING: dict[str, dict[str, float]] = {
    # Gemini
    "gemini-2.5-flash":   {"input": 0.15,  "output": 0.60},
    "gemini-2.0-flash":   {"input": 0.10,  "output": 0.40},
    "gemini-1.5-pro":     {"input": 1.25,  "output": 5.00},
    "gemini-1.5-flash":   {"input": 0.075, "output": 0.30},
    "gemma-3-27b-it":     {"input": 0.10,  "output": 0.10},
    "gemma-3-12b-it":     {"input": 0.05,  "output": 0.05},
    "gemma-3-4b-it":      {"input": 0.025, "output": 0.025},
    # OpenAI
    "gpt-4o":             {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":        {"input": 0.15,  "output": 0.60},
    "gpt-4-turbo":        {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo":      {"input": 0.50,  "output": 1.50},
    # Qwen (local / Fireworks pricing)
    "Qwen2.5-0.5B-Instruct": {"input": 0.00, "output": 0.00},
}
# fmt: on

_FALLBACK_PRICING = {"input": 1.00, "output": 3.00}  # conservative unknown-model estimate


def _price_per_token(model: str) -> dict[str, float]:
    for key in _PRICING:
        if key.lower() in model.lower() or model.lower() in key.lower():
            return _PRICING[key]
    return _FALLBACK_PRICING


# ---------------------------------------------------------------------------
# Per-call record
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    pipeline: str = "unknown"   # "rag" | "text2sql" | "unknown"


# ---------------------------------------------------------------------------
# Session-level tracker
# ---------------------------------------------------------------------------

@dataclass
class _ModelTotals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class CostTracker:
    """Thread-safe accumulator for token usage and cost across the process lifetime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[TokenUsage] = []
        self._by_model: dict[str, _ModelTotals] = {}

    # -- Public API -----------------------------------------------------------

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        pipeline: str = "unknown",
    ) -> TokenUsage:
        """
        Record a single LLM call.

        Returns a TokenUsage with the estimated cost so callers can log it
        immediately (e.g. with audit_logger).
        """
        pricing = _price_per_token(model)
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

        usage = TokenUsage(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            pipeline=pipeline,
        )

        with self._lock:
            self._calls.append(usage)
            if model not in self._by_model:
                self._by_model[model] = _ModelTotals()
            m = self._by_model[model]
            m.calls += 1
            m.input_tokens += input_tokens
            m.output_tokens += output_tokens
            m.cost_usd += cost

        return usage

    def estimate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Return estimated cost in USD without recording it."""
        pricing = _price_per_token(model)
        return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

    def summary(self) -> dict:
        """Return a snapshot of session-level totals."""
        with self._lock:
            total_input = sum(u.input_tokens for u in self._calls)
            total_output = sum(u.output_tokens for u in self._calls)
            total_cost = sum(u.cost_usd for u in self._calls)
            by_model = {
                m: {
                    "calls": t.calls,
                    "input_tokens": t.input_tokens,
                    "output_tokens": t.output_tokens,
                    "cost_usd": round(t.cost_usd, 6),
                }
                for m, t in self._by_model.items()
            }
        return {
            "calls": len(self._calls),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_cost_usd": round(total_cost, 6),
            "by_model": by_model,
        }

    def reset(self) -> None:
        """Clear all accumulated data (useful between test runs or sessions)."""
        with self._lock:
            self._calls.clear()
            self._by_model.clear()

    def get_model_price(self, model: str) -> dict[str, float]:
        """Return the input/output price per 1 M tokens for a model."""
        return _price_per_token(model)


# Singleton instance — import and use directly:
#   from observability.metrics.costs import cost_tracker
cost_tracker = CostTracker()
