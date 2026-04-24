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

if TYPE_CHECKING:
    from ...text2sql.db.databricks_service import DatabricksService

MAX_ATTEMPTS = 3


def sql_node(state: AgentState, *, data_service) -> dict:
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

    # Step 3: execute
    try:
        rows = execute_sql_query(sql, table_name, data_service)
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
