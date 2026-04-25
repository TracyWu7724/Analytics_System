"""
table_matching.py — keyword extraction + similarity scoring to pick the best
Databricks table for a natural-language question.

Approach:
  1. Strip stop-words from the question to get meaningful keywords.
  2. Score each table by comparing those keywords against the table's simple
     name (split on underscores/dots) using token-set fuzzy ratio.
  3. Boost tables whose name words appear verbatim in the question.
  4. Return the ranked list; callers take the top entry.
"""

from __future__ import annotations

import re
from typing import Any

from fuzzywuzzy import fuzz

try:
    from ..cache_service import db_cache
except ImportError:
    from cache_service import db_cache

# ── Stop-word list ────────────────────────────────────────────────────────────

_STOP_WORDS = {
    "a", "an", "the", "and", "or", "for", "of", "in", "on", "at", "to",
    "by", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "shall", "can", "need", "dare", "ought", "used",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us",
    "them", "my", "your", "his", "its", "our", "their",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other", "some",
    "such", "no", "not", "only", "same", "so", "than", "too", "very",
    "just", "but", "if", "with", "about", "against", "between", "into",
    "through", "during", "before", "after", "above", "below", "from", "up",
    "down", "out", "off", "over", "under", "again", "then", "once",
    # SQL-like words that appear in questions but aren't table name hints
    "show", "give", "list", "get", "find", "fetch", "return", "display",
    "tell", "explain", "describe", "select", "query", "table", "column",
    "row", "record", "data", "information", "info", "count", "total",
    "average", "sum", "max", "min", "number", "amount", "value", "me", "us",
}


def _extract_keywords(question: str) -> list[str]:
    """Return meaningful words from the question (lower-cased, stop-words removed)."""
    words = re.findall(r"[a-zA-Z]+", question.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


def _table_tokens(full_name: str) -> list[str]:
    """Split a qualified table name into lowercase tokens.

    e.g. 'chatbot_mw.default.sales_data' → ['chatbot', 'mw', 'default', 'sales', 'data']
    """
    return re.findall(r"[a-z]+", full_name.lower())


def _score(question_keywords: list[str], full_name: str, simple_name: str,
           schema: list[dict] | None = None) -> float:
    """
    Compute a similarity score (0–130) between question keywords and a table.

    Scoring layers:
      1. Fuzzy token-set ratio on table name tokens (0–100 base)
      2. +10 per keyword that verbatim matches a table-name token
      3. +15 per keyword that verbatim matches a column name (schema columns)
      4. +0.3 × fuzzy ratio of keywords against all column names joined
    """
    if not question_keywords:
        return 0.0

    keyword_str = " ".join(question_keywords)
    toks = _table_tokens(simple_name)
    tok_str = " ".join(toks)

    # Layer 1: base fuzzy ratio on table name
    base = fuzz.token_set_ratio(keyword_str, tok_str)

    # Layer 2: verbatim table-token bonus
    tok_set = set(toks)
    verbatim_hits = sum(1 for kw in question_keywords if kw in tok_set)
    bonus = verbatim_hits * 10

    # Layers 3 & 4: column-name scoring (uses cache — 0 cost if not cached)
    col_bonus = 0.0
    if schema:
        # Flatten all column name tokens
        col_tokens: set[str] = set()
        col_words: list[str] = []
        for col in schema:
            parts = re.findall(r"[a-z]+", col.get("name", "").lower())
            col_tokens.update(parts)
            col_words.extend(parts)

        col_str = " ".join(col_words)

        # Layer 3: verbatim column token bonus (weighted higher than table name)
        col_verbatim = sum(1 for kw in question_keywords if kw in col_tokens)
        col_bonus += col_verbatim * 15

        # Layer 4: fuzzy ratio against all column names
        col_bonus += fuzz.token_set_ratio(keyword_str, col_str) * 0.3

    return min(130.0, base + bonus + col_bonus)


# ── Public API ────────────────────────────────────────────────────────────────

def invalidate_table_cache() -> None:
    db_cache.invalidate_table_list()


def get_all_available_tables(service: Any) -> list[dict]:
    cached = db_cache.get_table_list(include_sql_server=True)
    if cached is not None:
        return cached

    table_list: list[dict] = []
    for full_name in service.get_table_names():
        simple_name = full_name.split(".")[-1]          # last segment
        schema      = ".".join(full_name.split(".")[:-1])
        table_list.append({
            "full_name":   full_name,
            "table_name":  simple_name,
            "schema":      schema,
            "description": simple_name.replace("_", " "),
            "source":      "databricks",
        })

    db_cache.set_table_list(table_list, include_sql_server=True, ttl=300)
    return table_list


def get_relevant_tables(
    question: str,
    service: Any,
    limit: int = 5,
) -> list[dict]:
    """
    Return tables ranked by keyword-similarity to the question.

    Scoring uses table name tokens, cached column name tokens, and (if available)
    the persistent inverted index's schema boost.
    """
    keywords = _extract_keywords(question)

    # Schema + history boost from inverted index (0 if index not ready)
    schema_boost: dict = {}
    history_boost: dict = {}
    try:
        from ..indexing.inverted_index import get_inverted_index
        idx = get_inverted_index()
        if idx is not None and idx.is_ready():
            schema_boost  = idx.score_tables_by_schema(question)
            history_boost = idx.score_tables_by_history(question)
    except Exception:
        pass

    scored = []
    for table in get_all_available_tables(service):
        # Pull schema from cache only (None if not yet cached — no extra I/O)
        schema = db_cache.get_table_schema(table["full_name"])
        score = _score(keywords, table["full_name"], table["table_name"], schema)
        score += schema_boost.get(table["full_name"], 0.0)
        score += history_boost.get(table["full_name"], 0.0)
        scored.append({**table, "score": score})
    scored.sort(key=lambda t: t["score"], reverse=True)
    return scored[:limit]


def find_best_table_match(question: str, service: Any) -> str | None:
    ranked = get_relevant_tables(question, service, limit=1)
    if not ranked:
        return None
    return str(ranked[0]["full_name"])


def extract_table_name_from_question(question: str, service: Any) -> str:
    return find_best_table_match(question, service) or service.db_schema
