"""
column_profiler.py — Decide whether to index a column's distinct values.

Columns that are high-cardinality (many distinct string values like UUIDs or
free-text) or numeric are not useful for the hallucination guard and would
bloat the value index.  This module gates indexing to only value-set columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_STRING_TYPES = {
    "string", "varchar", "char", "text", "nvarchar", "nchar",
    "clob", "tinytext", "mediumtext", "longtext",
}

MAX_CARDINALITY = 5_000  # skip columns with more than this many distinct values
MIN_AVG_LENGTH  = 1      # skip columns where average value length < 1 char
MAX_AVG_LENGTH  = 100    # skip free-text columns (very long values)


@dataclass
class ColumnProfile:
    table: str
    column: str
    col_type: str
    distinct_count: int
    avg_length: float
    should_index: bool
    reason: str


def is_string_type(col_type: str) -> bool:
    return col_type.lower().split("(")[0].strip() in _STRING_TYPES


def profile_column(
    table: str,
    col_name: str,
    col_type: str,
    data_service: Any,
    max_cardinality: int = MAX_CARDINALITY,
) -> ColumnProfile:
    """
    Query Databricks to determine whether this column should be indexed.
    Returns a ColumnProfile with should_index=True only for useful value-set cols.
    """
    if not is_string_type(col_type):
        return ColumnProfile(
            table=table, column=col_name, col_type=col_type,
            distinct_count=0, avg_length=0.0,
            should_index=False, reason="non-string type",
        )

    try:
        rows = data_service.execute_query(
            f"SELECT COUNT(DISTINCT `{col_name}`) AS cnt, "
            f"AVG(LENGTH(CAST(`{col_name}` AS STRING))) AS avg_len "
            f"FROM {table} WHERE `{col_name}` IS NOT NULL",
            custom_limit=1,
        )
        if not rows:
            return ColumnProfile(
                table=table, column=col_name, col_type=col_type,
                distinct_count=0, avg_length=0.0,
                should_index=False, reason="empty column",
            )
        cnt = int(rows[0].get("cnt", 0) or 0)
        avg_len = float(rows[0].get("avg_len", 0) or 0.0)
    except Exception as exc:
        return ColumnProfile(
            table=table, column=col_name, col_type=col_type,
            distinct_count=0, avg_length=0.0,
            should_index=False, reason=f"profile query failed: {exc}",
        )

    if cnt > max_cardinality:
        return ColumnProfile(
            table=table, column=col_name, col_type=col_type,
            distinct_count=cnt, avg_length=avg_len,
            should_index=False, reason=f"high cardinality ({cnt} > {max_cardinality})",
        )
    if avg_len > MAX_AVG_LENGTH:
        return ColumnProfile(
            table=table, column=col_name, col_type=col_type,
            distinct_count=cnt, avg_length=avg_len,
            should_index=False, reason=f"free-text column (avg length {avg_len:.0f})",
        )
    if cnt == 0:
        return ColumnProfile(
            table=table, column=col_name, col_type=col_type,
            distinct_count=0, avg_length=0.0,
            should_index=False, reason="no distinct values",
        )

    return ColumnProfile(
        table=table, column=col_name, col_type=col_type,
        distinct_count=cnt, avg_length=avg_len,
        should_index=True, reason="ok",
    )
