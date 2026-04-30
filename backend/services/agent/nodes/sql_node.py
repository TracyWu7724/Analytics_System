"""
nodes/sql_node.py — SQL pipeline node with self-correction loop.

Flow (internal to this node):
  pick table → get columns → generate SQL → execute
      ↑                                         ↓ error (attempts < MAX_ATTEMPTS)
      └──────────── fix SQL with error ←────────┘
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..state import AgentState
from ..tools.sql_tool import (
    execute_sql_query,
    generate_sql_query,
    get_columns,
    get_multi_table_schema,
    pick_table,
    pick_tables,
)
from ...text2sql.generation.sql_hallucination_guard import (
    diagnose_empty_result,
    validate_column_semantics,
    validate_schema,
    validate_query_values,
    validate_sql_values,
)
from ...text2sql.query_value_extractor import extract_filter_candidates
from ...text2sql.indexing.history_question_indexing import index_question
from ..progress import emit as _progress

if TYPE_CHECKING:
    from ...text2sql.db.databricks_service import DatabricksService
    from ...text2sql.indexing.inverted_index import InvertedIndex

MAX_ATTEMPTS = 3


def sql_node(state: AgentState, *, data_service, value_index=None, product_index=None) -> dict:
    """
    LangGraph node: run the SQL pipeline with up to MAX_ATTEMPTS self-corrections.

    Parameters
    ----------
    data_service : DatabricksService
        Injected at graph-build time via functools.partial.
    """
    question = state["question"]
    llm_model = state.get("llm_model", "gemini-2.5-flash")
    uploaded_table = state.get("uploaded_table")
    history = state.get("history") or []
    attempts = state.get("sql_attempts", 0)
    previous_sql = state.get("sql_query")
    previous_error = state.get("sql_error")
    denied_tables: list[str] = state.get("denied_tables") or []
    session_id: str = state.get("session_id", "")
    user_id: str = state.get("user_id", "")

    _progress(session_id, "routing", "Understanding context...")

    # Step 1: pick tables (reuse cached value if we're correcting)
    cached_tables: list[str] = state.get("sql_tables") or []
    if cached_tables:
        table_name = cached_tables[0]
        all_tables  = cached_tables
    else:
        try:
            all_tables = pick_tables(question, data_service, value_index=value_index)
        except Exception:
            all_tables = []
        table_name = all_tables[0] if all_tables else pick_table(question, data_service, uploaded_table)
        if table_name not in all_tables:
            all_tables = [table_name]

    # Access control — block if the primary table matches a denied pattern
    if denied_tables and any(p.lower() in table_name.lower() for p in denied_tables):
        return {
            "sql_table":  table_name,
            "sql_tables": all_tables,
            "sql_query":  None,
            "sql_rows":   None,
            "sql_error":  f"Access denied: your role does not have permission to query '{table_name}'.",
            "sql_attempts": attempts + 1,
        }

    _progress(session_id, "columns", "Retrieving table and columns...")

    # Fetch schema for primary table
    columns = get_columns(table_name, data_service)
    import logging as _logging
    _logging.getLogger(__name__).info(
        f"[sql_node] table={table_name!r}  columns={columns}"
    )

    # Fetch schema for additional tables (for JOIN support)
    extra_tables: dict[str, list[str]] = {}
    if len(all_tables) > 1:
        extra_tables = get_multi_table_schema(all_tables[1:], data_service)

    # Step 2: Resolve product mentions first so that value validation below
    # operates on canonical DB names rather than raw question text.
    # e.g. "LOCTITE 243" → "LOCTITE 243 Threadlocker Blue" before any checks.
    #
    # Brand-only mentions without a product number (no digits, e.g. "Loctite",
    # "Loctite adhesives") are intentionally skipped — they should generate
    # LIKE '%loctite%' patterns, not exact-value filters.
    product_hints: dict = {}
    import re as _re_digit
    _HAS_DIGIT = _re_digit.compile(r'\d')
    if product_index is not None and product_index.is_ready() and attempts == 0:
        for cand in extract_filter_candidates(question):
            if not _HAS_DIGIT.search(cand["text"]):
                continue   # brand-only name — skip product index resolution
            canonical = product_index.resolve(cand["text"], table=table_name or None)
            if canonical is None and table_name:
                # Primary table has no products (e.g. it's a supplier/budget table).
                # Fall back to any table in the product index — the LLM will use
                # the canonical name in whatever JOIN table it picks.
                canonical = product_index.resolve(cand["text"], table=None)
            if canonical and canonical.lower() != cand["text"].lower():
                product_hints[cand["text"]] = canonical

    # Step 1b: Pre-SQL value check — verify named entities exist in the DB.
    # Candidates already resolved by product_index are skipped (they're confirmed
    # to exist). Remaining candidates are checked against the value index.
    # Only runs on first attempt to avoid redundant checks on retries.
    if attempts == 0 and value_index is not None:
        resolved_texts = {v.lower() for v in product_hints.values()}
        question_for_val = question
        # Replace resolved product mentions with their canonical forms so the
        # value check searches for what the SQL will actually filter on.
        for raw, canonical in product_hints.items():
            question_for_val = question_for_val.replace(raw, canonical)

        val_ok, val_msg = validate_query_values(
            question_for_val, value_index, table_name=table_name,
            session_id=session_id, user_id=user_id,
        )
        if not val_ok:
            return {
                "sql_table": table_name,
                "sql_query": None,
                "sql_rows":  [],
                "sql_error": None,
                "sql_attempts": attempts + 1,
                "final_answer": val_msg,
            }

    _progress(session_id, "generating", "Generating SQL...")

    # Step 3: generate (or fix) SQL
    try:
        sql = generate_sql_query(
            question,
            table_name,
            columns,
            llm_model=llm_model,
            previous_sql=previous_sql if attempts > 0 else None,
            previous_error=previous_error if attempts > 0 else None,
            history=history,
            product_hints=product_hints if product_hints else None,
            extra_tables=extra_tables if extra_tables else None,
        )
    except Exception as e:
        return {
            "sql_table":  table_name,
            "sql_tables": all_tables,
            "sql_query":  previous_sql,
            "sql_rows":   None,
            "sql_error":  f"SQL generation failed: {e}",
            "sql_attempts": attempts + 1,
        }

    # Deterministic table name correction — ensure the fully-qualified table
    # name is used in the SQL.  The LLM sometimes drops the table part and
    # writes only catalog.schema (e.g. FROM chatbot_mw.default).
    if table_name and table_name.lower() not in sql.lower():
        parts = table_name.rsplit(".", 1)
        if len(parts) == 2:
            prefix_lower = parts[0].lower()
            sql_lower    = sql.lower()
            out: list[str] = []
            cursor = 0
            i = sql_lower.find(prefix_lower)
            while i != -1:
                end = i + len(parts[0])
                if end < len(sql) and sql[end] == '.':
                    # Already fully qualified — skip
                    out.append(sql[cursor:end])
                    cursor = end
                else:
                    # Truncated name — replace with full table name
                    out.append(sql[cursor:i])
                    out.append(table_name)
                    cursor = end
                i = sql_lower.find(prefix_lower, cursor)
            out.append(sql[cursor:])
            sql = ''.join(out)

    # Deterministic product name correction — scan WHERE-clause literals and
    # replace them with canonical DB names using the product index.
    # e.g.  WHERE Product_Name = 'LOCTITE 243'
    #     → WHERE Product_Name = 'LOCTITE 243 Threadlocker Blue'
    if product_index is not None and product_index.is_ready():
        sql = product_index.correct_sql_values(sql, table=table_name)

    # Step 3a: Schema hallucination check
    # extra_columns: columns from JOIN tables — valid identifiers, not hallucinations
    all_extra_cols = [c for cols in extra_tables.values() for c in cols] if extra_tables else []
    schema_ok, schema_hint = validate_schema(
        sql, table_name, columns, question=question,
        session_id=session_id, user_id=user_id,
        extra_columns=all_extra_cols or None,
    )
    if not schema_ok:
        return {
            "sql_table":  table_name,
            "sql_tables": all_tables,
            "sql_query":  sql,
            "sql_rows":   None,
            "sql_error":  schema_hint,
            "sql_attempts": attempts + 1,
        }

    # Step 3b: Column semantic check — embedding-based comparison of question
    # intent vs. columns actually used in the SELECT clause.
    # e.g. question asks "profit" but SQL uses SUM(price) → flag and retry.
    sem_ok, sem_hint = validate_column_semantics(
        question, sql, columns, table_name,
        session_id=session_id, user_id=user_id,
    )
    if not sem_ok:
        return {
            "sql_table":  table_name,
            "sql_tables": all_tables,
            "sql_query":  sql,
            "sql_rows":   None,
            "sql_error":  sem_hint,
            "sql_attempts": attempts + 1,
        }

    # Step 3c: Post-SQL value check — verify WHERE literals exist in the index.
    # More precise than the pre-check because literals come directly from the SQL.
    # If product_hints has a canonical name for the literal, build a targeted
    # correction hint and set sql_error so the retry loop rewrites the SQL.
    if value_index is not None:
        sql_val_ok, sql_val_msg = validate_sql_values(
            sql, table_name, value_index,
            question=question, session_id=session_id, user_id=user_id,
        )
        if not sql_val_ok:
            # Build a correction hint: if we know the canonical name, tell the
            # LLM exactly what to replace so the next attempt uses it.
            correction_parts = []
            for raw, canonical in product_hints.items():
                if raw.lower() in sql.lower():
                    correction_parts.append(
                        f"Replace '{raw}' with '{canonical}' in the WHERE clause."
                    )
            if correction_parts:
                correction_hint = (
                    "Value not found in database. " + " ".join(correction_parts)
                )
            else:
                correction_hint = sql_val_msg

            return {
                "sql_table":  table_name,
                "sql_tables": all_tables,
                "sql_query":  sql,
                "sql_rows":   None,
                "sql_error":  correction_hint,
                "sql_attempts": attempts + 1,
            }

    _progress(session_id, "executing", "Executing SQL...")

    # Step 3: execute
    try:
        rows = execute_sql_query(sql, table_name, data_service)
        _progress(session_id, "validating", "Validating result...")

        # Step 3a: Empty-result diagnosis
        # Treat as terminal (not retryable) — the SQL was valid but the entity
        # simply doesn't exist in the data.  Retrying risks the LLM substituting
        # a different person/value from the sample list (hallucination).
        if rows is not None and len(rows) == 0:
            user_msg = diagnose_empty_result(
                sql, table_name, data_service,
                question=question, session_id=session_id, user_id=user_id,
            )
            return {
                "sql_table":  table_name,
                "sql_tables": all_tables,
                "sql_query":  sql,
                "sql_rows":   [],
                "sql_error":  None,
                "sql_attempts": attempts + 1,
                "final_answer": user_msg,
            }

        # Record in both SQLite history and InvertedIndex via unified indexer
        index_question(question, data_service, sql=sql, table_name=table_name)

        return {
            "sql_table":  table_name,
            "sql_tables": all_tables,
            "sql_query":  sql,
            "sql_rows":   rows,
            "sql_error":  None,
            "sql_attempts": attempts + 1,
        }
    except Exception as e:
        return {
            "sql_table":  table_name,
            "sql_tables": all_tables,
            "sql_query":  sql,
            "sql_rows":   None,
            "sql_error":  str(e),
            "sql_attempts": attempts + 1,
        }


def should_retry_sql(state: AgentState) -> str:
    """
    Conditional edge after sql_node.

    Returns
    -------
    "retry_sql"   — execution failed and we have retries left
    "rag_node"    — route is "both", move to RAG next
    "synthesizer" — route is "both" and RAG already ran
    "end"         — done (success or out of retries)
    """
    has_error = bool(state.get("sql_error"))
    attempts = state.get("sql_attempts", 0)
    route = state.get("route", "sql")

    if has_error and attempts < MAX_ATTEMPTS:
        return "retry_sql"

    # If both pipelines are needed and RAG hasn't run yet
    if route == "both" and state.get("rag_answer") is None:
        return "rag_node"

    # If both pipelines needed and RAG already ran → synthesize
    if route == "both" and state.get("rag_answer") is not None:
        return "synthesizer"

    return "end"
