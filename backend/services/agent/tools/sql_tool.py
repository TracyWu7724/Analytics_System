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


def decide_table_count(
    question: str,
    value_index,
) -> tuple[int, set[str]]:
    """
    Decide how many tables to retrieve (1 or 3) and return schema-matched table hints.

    Returns
    -------
    (count, schema_tables)
        count        — 1 or 3 tables to fetch from get_relevant_tables
        schema_tables — tables whose column names specifically match the question's
                        metric/dimension intent; used to reorder candidates so the
                        most schema-relevant table is selected as primary.

    Logic
    -----
    1. Value candidates (PERSON, ORG, product names) → look up in value index
       to find which table each entity belongs to (value_tables).
    2. Remaining tokens → look up in schema index to find tables with matching
       column names (schema_tables). Only non-ubiquitous columns count.
    3. If value_tables ∪ schema_tables spans >1 table → JOIN likely → return 3.
    4. schema_tables is returned so pick_tables can prioritise the right table.

    Falls back to (1, set()) on any error.
    """
    if value_index is None or not value_index.is_ready():
        return 1, set()

    try:
        try:
            from ...text2sql.query_value_extractor import extract_filter_candidates
        except ImportError:
            from text2sql.query_value_extractor import extract_filter_candidates

        import re

        _SCHEMA_STOPWORDS = {
            "loctite", "product", "products", "adhesive", "adhesives",
            "threadlocker", "threadlockers", "sealant", "retaining", "structural",
            "item", "items", "material", "materials", "part", "parts",
            "name", "id", "date", "type", "category", "status", "description",
        }

        # Step 1: value candidates → find which table each entity lives in
        value_candidates = extract_filter_candidates(question)
        value_tables: set[str] = set()
        for cand in value_candidates:
            result = value_index.search_value(cand["text"])
            if result.found and result.top_matches:
                value_tables.add(result.top_matches[0]["table"])

        # Step 2: schema tokens → find tables with matching column names
        value_spans = {c["text"].lower() for c in value_candidates}
        clean = question.lower()
        for span in sorted(value_spans, key=len, reverse=True):
            clean = clean.replace(span, " ")
        tokens = [
            t for t in re.split(r"[^a-z0-9]+", clean)
            if len(t) > 2 and t not in _SCHEMA_STOPWORDS
        ]

        with value_index._lock:
            all_indexed_tables = {
                tbl
                for postings in value_index._schema.values()
                for tbl, _ in postings
            }
            n_total = len(all_indexed_tables)

            # ── Column-name schema matching ───────────────────────────────────
            schema_tables: set[str] = set()
            for tok in tokens:
                postings = value_index._schema.get(tok, [])
                tok_tables = {tbl for tbl, _ in postings}
                if tok_tables and len(tok_tables) < n_total:
                    schema_tables |= tok_tables

            # ── Table-name matching ───────────────────────────────────────────
            # Column-name matching misses questions like "inventory below 100"
            # where "inventory" is in the TABLE name (loctite_inventory_tracker)
            # but not in any column name. Build a reverse map: table-name-token
            # → full table name, then check question tokens against it.
            table_name_tokens: dict[str, set[str]] = {}  # tok → {full_table_name}
            for tbl in all_indexed_tables:
                simple = tbl.split(".")[-1]   # last segment, e.g. loctite_inventory_tracker
                for tok in re.split(r"[^a-z0-9]+", simple.lower()):
                    if len(tok) > 2 and tok not in _SCHEMA_STOPWORDS:
                        table_name_tokens.setdefault(tok, set()).add(tbl)

            for tok in tokens:
                matched = table_name_tokens.get(tok, set())
                if not matched:
                    # Prefix/plural match: "projects" → "project", "suppliers" → "supplier"
                    for tbl_tok, tbls in table_name_tokens.items():
                        if tok.startswith(tbl_tok) or tbl_tok.startswith(tok):
                            matched = tbls
                            break
                if matched and len(matched) < n_total:   # skip tokens shared by all tables
                    schema_tables |= matched

        all_matched = value_tables | schema_tables
        count = 3 if len(all_matched) > 1 else 1
        return count, schema_tables

    except Exception:
        return 1, set()  # safe fallback


def pick_table(
    question: str,
    data_service: DatabricksService,
    uploaded_table: Optional[str] = None,
) -> str:
    """Select the single best Databricks table for the question."""
    candidates = get_relevant_tables(question, data_service, limit=3)
    if candidates:
        return candidates[0]["full_name"]
    return extract_table_name_from_question(question, data_service)


def pick_tables(
    question: str,
    data_service: DatabricksService,
    value_index=None,
) -> list[str]:
    """
    Return 1 or up to 3 relevant tables, ordered so the most schema-relevant
    table is first (primary table for SQL generation).

    Uses decide_table_count to determine how many tables to fetch, then
    reorders them so tables whose column names match the question's metric/
    dimension intent come before tables matched only via entity values or
    fuzzy name scoring.

    Example: "inventory below 100 units" → schema_tables = {loctite_inventory_tracker}
    → that table is sorted to position 0 even if the fuzzy scorer ranks
    loctite_sales_data higher due to history.
    """
    k, schema_tables = decide_table_count(question, value_index)
    candidates = get_relevant_tables(question, data_service, limit=k)
    if not candidates:
        return []

    result = [c["full_name"] for c in candidates]

    # Reorder: tables whose column/table names specifically match the question go first.
    # Among tied schema-matched tables, prefer the one whose matching token appears
    # EARLIEST in the question — that token is usually the entity being queried
    # (e.g. "projects" in "how many projects whose inventory < 200" → project_budget
    #  wins over loctite_inventory_tracker even though "inventory" also matches).
    if schema_tables:
        import re as _re
        q_tokens = [t for t in _re.split(r"[^a-z0-9]+", question.lower()) if len(t) > 2]

        def _schema_rank(full_name: str) -> tuple:
            for hint in schema_tables:
                if (full_name == hint
                        or full_name.endswith("." + hint)
                        or hint.endswith("." + full_name)):
                    # Find earliest position of any matching token in the question.
                    # Use prefix match so "project" matches question token "projects".
                    simple_toks = [
                        t for t in _re.split(r"[^a-z0-9]+", hint.split(".")[-1].lower())
                        if len(t) > 2
                    ]
                    best_pos = len(q_tokens)   # default: end of question
                    for qi, qt in enumerate(q_tokens):
                        for ht in simple_toks:
                            if qt == ht or qt.startswith(ht) or ht.startswith(qt):
                                best_pos = min(best_pos, qi)
                    return (0, best_pos)   # schema-matched; lower pos = earlier mention = higher priority
            return (1, 0)                  # not schema-matched → after all schema tables

        result.sort(key=_schema_rank)

    return result


def get_columns(table_name: str, data_service: DatabricksService) -> Optional[list[str]]:
    """Return column names for a Databricks table."""
    schema = data_service.get_table_schema(table_name)
    return [col["name"] for col in schema] if schema else None


def get_multi_table_schema(
    table_names: list[str],
    data_service: DatabricksService,
) -> dict[str, list[str]]:
    """Return {table_name: [col, ...]} for every table in the list."""
    result = {}
    for tname in table_names:
        cols = get_columns(tname, data_service)
        if cols:
            result[tname] = cols
    return result


def generate_sql_query(
    question: str,
    table_name: str,
    columns: Optional[list[str]] = None,
    custom_limit: Optional[int] = None,
    llm_model: str = "gpt-4o",
    previous_sql: Optional[str] = None,
    previous_error: Optional[str] = None,
    history: Optional[list[dict]] = None,
    product_hints: Optional[dict] = None,
    extra_tables: Optional[dict[str, list[str]]] = None,
    mdl_context: Optional[str] = None,
) -> str:
    """
    Generate (or fix) a SQL query for Databricks.

    Parameters
    ----------
    extra_tables : {table_name: [col, ...]}
        Additional tables available for JOIN beyond the primary table.
    """
    if previous_sql and previous_error:
        correction_note = (
            f"\n\nThe previous query failed:\n"
            f"SQL: {previous_sql}\n"
            f"Error: {previous_error}\n"
            f"Fix the query so it runs correctly."
        )
        q = question + correction_note
    else:
        q = question

    raw = generate_sql(
        q, table_name, columns, custom_limit, llm_model,
        history=history, product_hints=product_hints,
        extra_tables=extra_tables, mdl_context=mdl_context,
    )
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
