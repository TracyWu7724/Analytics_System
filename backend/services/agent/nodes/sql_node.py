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
    pick_table,
)
from ...text2sql.generation.sql_hallucination_guard import (
    diagnose_empty_result,
    validate_logic,
    validate_schema,
    validate_query_values,
    validate_sql_values,
)
from ...text2sql.indexing.history_question_indexing import index_question

if TYPE_CHECKING:
    from ...text2sql.db.databricks_service import DatabricksService
    from ...text2sql.indexing.inverted_index import InvertedIndex

MAX_ATTEMPTS = 3


def sql_node(state: AgentState, *, data_service, value_index=None) -> dict:
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
    attempts = state.get("sql_attempts", 0)
    previous_sql = state.get("sql_query")
    previous_error = state.get("sql_error")
    denied_tables: list[str] = state.get("denied_tables") or []
    session_id: str = state.get("session_id", "")
    user_id: str = state.get("user_id", "")

    # Step 1: pick table (reuse cached value if we're correcting)
    table_name = state.get("sql_table") or pick_table(question, data_service, uploaded_table)

    # Access control — block if the table matches a denied pattern
    if denied_tables and any(p.lower() in table_name.lower() for p in denied_tables):
        return {
            "sql_table": table_name,
            "sql_query": None,
            "sql_rows": None,
            "sql_error": f"Access denied: your role does not have permission to query '{table_name}'.",
            "sql_attempts": attempts + 1,
        }

    columns = get_columns(table_name, data_service)

    # Step 1b: Pre-SQL value check — extract named entities from question and
    # verify they exist in the indexed distinct values (first attempt only).
    # Avoids wasting an LLM call when the queried entity clearly doesn't exist.
    if attempts == 0 and value_index is not None:
        val_ok, val_msg = validate_query_values(
            question, value_index, table_name=table_name,
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

    # Step 2: generate (or fix) SQL
    try:
        sql = generate_sql_query(
            question,
            table_name,
            columns,
            llm_model=llm_model,
            previous_sql=previous_sql if attempts > 0 else None,
            previous_error=previous_error if attempts > 0 else None,
        )
    except Exception as e:
        return {
            "sql_table": table_name,
            "sql_query": previous_sql,
            "sql_rows": None,
            "sql_error": f"SQL generation failed: {e}",
            "sql_attempts": attempts + 1,
        }

    # Step 2a: Schema hallucination check
    schema_ok, schema_hint = validate_schema(
        sql, table_name, columns, question=question,
        session_id=session_id, user_id=user_id,
    )
    if not schema_ok:
        return {
            "sql_table": table_name,
            "sql_query": sql,
            "sql_rows": None,
            "sql_error": schema_hint,
            "sql_attempts": attempts + 1,
        }

    # Step 2b: Post-SQL value check — verify WHERE literals exist in the index.
    # More precise than the pre-check because literals come directly from the SQL.
    if value_index is not None:
        sql_val_ok, sql_val_msg = validate_sql_values(
            sql, table_name, value_index,
            question=question, session_id=session_id, user_id=user_id,
        )
        if not sql_val_ok:
            return {
                "sql_table": table_name,
                "sql_query": sql,
                "sql_rows":  [],
                "sql_error": None,
                "sql_attempts": attempts + 1,
                "final_answer": sql_val_msg,
            }

    # Step 2d: Logical hallucination check (first attempt only — LLM call is costly)
    if attempts == 0:
        logic_ok, logic_hint = validate_logic(
            question, sql, table_name, columns,
            llm_model=llm_model,
            session_id=session_id, user_id=user_id,
        )
        if not logic_ok:
            return {
                "sql_table": table_name,
                "sql_query": sql,
                "sql_rows": None,
                "sql_error": logic_hint,
                "sql_attempts": attempts + 1,
            }

    # Step 3: execute
    try:
        rows = execute_sql_query(sql, table_name, data_service)

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
                "sql_table": table_name,
                "sql_query": sql,
                "sql_rows": [],      # empty but valid — stops retry loop
                "sql_error": None,
                "sql_attempts": attempts + 1,
                "final_answer": user_msg,
            }

        # Record in both SQLite history and InvertedIndex via unified indexer
        index_question(question, data_service, sql=sql, table_name=table_name)

        return {
            "sql_table": table_name,
            "sql_query": sql,
            "sql_rows": rows,
            "sql_error": None,
            "sql_attempts": attempts + 1,
        }
    except Exception as e:
        return {
            "sql_table": table_name,
            "sql_query": sql,
            "sql_rows": None,
            "sql_error": str(e),
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
