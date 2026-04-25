"""
tools/sql_tool.py — thin wrapper around the v1 Text2SQL pipeline.
"""

from __future__ import annotations

from typing import Optional

try:
    from ...text2sql.db.databricks_service import DatabricksService
    from ...text2sql.generation.sql_correction import clean_sql_query
    from ...text2sql.generation.sql_generation import generate_sql
    from ...text2sql.retrieval.table_matching import (
        extract_table_name_from_question,
        get_relevant_tables,
    )
except ImportError:
    from db.databricks_service import DatabricksService
    from generation.sql_correction import clean_sql_query
    from generation.sql_generation import generate_sql
    from retrieval.table_matching import (
        extract_table_name_from_question,
        get_relevant_tables,
    )


def pick_table(
    question: str,
    data_service: DatabricksService,
    uploaded_table: Optional[str] = None,
) -> str:
    """Select the best Databricks table for the question."""
    candidates = get_relevant_tables(question, data_service, limit=3)
    if candidates:
        return candidates[0]["full_name"]
    return extract_table_name_from_question(question, data_service)


def get_columns(table_name: str, data_service: DatabricksService) -> Optional[list[str]]:
    """Return column names for a Databricks table."""
    schema = data_service.get_table_schema(table_name)
    return [col["name"] for col in schema] if schema else None


def generate_sql_query(
    question: str,
    table_name: str,
    columns: Optional[list[str]] = None,
    custom_limit: Optional[int] = None,
    llm_model: str = "gpt-5.4",
    previous_sql: Optional[str] = None,
    previous_error: Optional[str] = None,
) -> str:
    """Generate (or fix) a SQL query for Databricks."""
    if previous_sql and previous_error:
        correction_note = (
            f"\n\nThe previous query failed:\n"
            f"SQL: {previous_sql}\n"
            f"Error: {previous_error}\n"
            f"Fix the query so it runs correctly."
        )
        raw = generate_sql(question + correction_note, table_name, columns, custom_limit, llm_model)
    else:
        raw = generate_sql(question, table_name, columns, custom_limit, llm_model)
    return clean_sql_query(raw)


def execute_sql_query(
    sql: str,
    table_name: str,
    data_service: DatabricksService,
    timeout_seconds: int = 60,
    custom_limit: Optional[int] = None,
) -> list[dict]:
    """Execute a SQL query on Databricks and return rows as list of dicts."""
    return data_service.execute_query(
        sql, timeout_seconds=timeout_seconds, custom_limit=custom_limit
    )
