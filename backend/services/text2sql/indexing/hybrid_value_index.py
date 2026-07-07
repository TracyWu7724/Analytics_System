"""
hybrid_value_index.py — Thin facade over InvertedIndex that adds:
  - column profiling gate (skip high-cardinality / numeric columns)
  - canonical value normalization (LOCTITE 243 → loctite 243)
  - LLM judge fallback via entity_matcher
  - backward-compatible search_value() / is_ready() / stats() API
"""

from __future__ import annotations

import logging
from typing import Optional

from .inverted_index import InvertedIndex, SearchResult, init_inverted_index
from .value_canonicalizer import canonical_variants, canonicalize
from .column_profiler import profile_column

logger = logging.getLogger(__name__)

_hybrid_instance: Optional["HybridValueIndex"] = None


class HybridValueIndex:
    """
    Wraps InvertedIndex to add canonicalization and profiling.

    The profiling gate is applied at build time (inside _build_sync_patched).
    The canonicalization is applied at both index time and query time.
    """

    def __init__(self, base: InvertedIndex):
        self._base = base

    # ── Passthrough API (backward-compatible) ─────────────────────────────────

    def search_value(self, candidate: str, table: Optional[str] = None) -> SearchResult:
        """Search for `candidate`, also searching its canonical form."""
        result = self._base.search_value(candidate, table=table)
        if result.found:
            return result
        # Try canonical form
        canon = canonicalize(candidate)
        if canon != candidate.strip().lower():
            return self._base.search_value(canon, table=table)
        return result

    def is_ready(self) -> bool:
        return self._base.is_ready()

    def stats(self) -> dict:
        return self._base.stats()

    def score_tables_by_schema(self, question: str) -> dict:
        return self._base.score_tables_by_schema(question)

    def score_tables_by_history(self, question: str) -> dict:
        return self._base.score_tables_by_history(question)

    def add_question(self, question: str, table: str) -> None:
        self._base.add_question(question, table)

    def add_value(self, table: str, col: str, value: str) -> None:
        for v in canonical_variants(value):
            self._base.add_value(table, col, v)

    def remove_value(self, table: str, col: str, value: str) -> None:
        self._base.remove_value(table, col, value)

    def rebuild(self, data_service, background: bool = True) -> None:
        self._base.rebuild(data_service, background=background)

    def load_or_build(self, data_service, background: bool = True) -> None:
        self._base.load_or_build(data_service, background=background)


def init_hybrid_index(
    data_service,
    index_dir: str = "",
    embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    background: bool = True,
) -> HybridValueIndex:
    global _hybrid_instance
    base = init_inverted_index(
        data_service,
        index_dir=index_dir,
        embed_model_name=embed_model_name,
        background=background,
    )
    _hybrid_instance = HybridValueIndex(base)
    return _hybrid_instance


def get_hybrid_index() -> Optional[HybridValueIndex]:
    return _hybrid_instance
