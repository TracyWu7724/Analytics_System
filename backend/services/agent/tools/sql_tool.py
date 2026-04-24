"""
tools/sql_tool.py — thin wrapper around the v1 Text2SQL pipeline.

Exposes two callables used by the SQL node:
  - generate_sql_query(question, table_name, ...) → str
  - execute_sql(sql, table_name, data_service, ...) → list[dict]

Keeping these as plain functions (not LangChain tools) so the SQL node
can call them directly and control the self-correction loop itself.
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
    """Select the best table for the question."""
    if uploaded_table:
        return uploaded_table
    candidates = get_relevant_tables(question, data_service, limit=3)
    if candidates:
        return candidates[0]["full_name"]
    return extract_table_name_from_question(question, data_service)


def get_columns(table_name: str, data_service: DatabricksService) -> Optional[list[str]]:
    """Return column names for a table, or None if unavailable."""
    if table_name.startswith("uploaded_"):
        try:
            from ...text2sql.db.upload_service import UploadService
        except ImportError:
            from db.upload_service import UploadService
        svc = UploadService(data_service)
        return svc.get_uploaded_table_columns(table_name, data_service.local_db_path)
    schema = data_service.get_table_schema(table_name)
    return [col["name"] for col in schema] if schema else None


def generate_sql_query(
    question: str,
    table_name: str,
    columns: Optional[list[str]] = None,
    custom_limit: Optional[int] = None,
    llm_model: str = "gemini-2.5-flash",
    previous_sql: Optional[str] = None,
    previous_error: Optional[str] = None,
) -> str:
    """
    Generate (or fix) a SQL query.

    If previous_sql and previous_error are provided the prompt includes the
    failing query and its error so the LLM can self-correct.
    """
    if previous_sql and previous_error:
        # Build a correction prompt and call generate_sql with it injected
        correction_note = (
            f"\n\nThe previous query failed:\n"
            f"SQL: {previous_sql}\n"
            f"Error: {previous_error}\n"
            f"Fix the query so it runs correctly."
        )
        corrected_question = question + correction_note
        raw = generate_sql(corrected_question, table_name, columns, custom_limit, llm_model)
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
    """Execute a SQL query and return rows as list of dicts."""
    if table_name.startswith("uploaded_"):
        return data_service.query_uploaded_table(sql)
    return data_service.execute_query(
        sql, timeout_seconds=timeout_seconds, custom_limit=custom_limit
    )
