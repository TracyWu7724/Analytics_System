"""
mdl_enricher.py — Enrich a user question with MDL context before SQL generation.

Given a raw question, this module:
  1. Detects which metrics the question references (by name or synonym).
  2. Detects which tables are referenced and what joins are available.
  3. Builds an MDL context block to inject into the SQL generation prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .mdl_loader import MDLConfig, MetricDef, JoinDef, load_mdl


@dataclass
class EnrichedQuestion:
    original: str
    mdl_metrics: list[MetricDef] = field(default_factory=list)
    mdl_joins: list[JoinDef] = field(default_factory=list)
    context_block: str = ""          # ready to inject into the SQL prompt


def enrich_question(question: str, mdl: Optional[MDLConfig] = None) -> EnrichedQuestion:
    """
    Return an EnrichedQuestion that annotates which MDL metrics and joins
    are relevant to the question.
    """
    if mdl is None:
        mdl = load_mdl()
    if mdl is None:
        return EnrichedQuestion(original=question)

    q_lower = question.lower()
    words = set(re.findall(r"\b\w+\b", q_lower))

    # ── Metric detection ──────────────────────────────────────────────────────
    matched_metrics: list[MetricDef] = []
    seen_metric_names: set[str] = set()
    for m in mdl.metrics:
        if m.name.lower() in seen_metric_names:
            continue
        match = any(
            syn.lower() in q_lower
            for syn in [m.name] + m.synonyms
            if len(syn) > 2
        )
        if match:
            matched_metrics.append(m)
            seen_metric_names.add(m.name.lower())

    # ── Table synonym detection for join hints ─────��──────────────────────────
    referenced_tables: set[str] = set()
    for tbl, syns in mdl.synonyms.items():
        if tbl.lower() in q_lower or any(s.lower() in q_lower for s in syns):
            referenced_tables.add(tbl.lower())

    matched_joins: list[JoinDef] = []
    if len(referenced_tables) >= 2:
        for j in mdl.joins:
            if j.left_table.lower() in referenced_tables and j.right_table.lower() in referenced_tables:
                matched_joins.append(j)

    if not matched_metrics and not matched_joins:
        return EnrichedQuestion(original=question)

    # ── Build context block ─────────────────���─────────────────────────────────
    lines: list[str] = ["## Semantic Layer (MDL)"]

    if matched_metrics:
        lines.append("### Metric Definitions (use these exact SQL expressions)")
        for m in matched_metrics:
            lines.append(f"- **{m.name}**: `{m.expression}`  — {m.description}")

    if matched_joins:
        lines.append("### Join Relationships")
        for j in matched_joins:
            lines.append(f"- {j.left_table} JOIN {j.right_table} ON {j.on}")

    context_block = "\n".join(lines)
    return EnrichedQuestion(
        original=question,
        mdl_metrics=matched_metrics,
        mdl_joins=matched_joins,
        context_block=context_block,
    )
