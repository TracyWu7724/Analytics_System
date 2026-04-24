import re
import sys
import os

from .llm_registry import DEFAULT_LLM_MODEL, get_llm

# Optional observability — no-op if the package isn't on sys.path
try:
    _obs_root = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
    if _obs_root not in sys.path:
        sys.path.insert(0, _obs_root)
    from observability.metrics.costs import cost_tracker as _cost_tracker
except Exception:
    _cost_tracker = None


def detect_large_dataset_request(question: str) -> tuple[bool, int | None, int]:
    question_lower = question.lower()
    wants_all = any(
        keyword in question_lower
        for keyword in ["all rows", "all data", "all records", "everything", "complete dataset", "entire table", "full table"]
    )

    custom_limit = None
    for pattern in [r"(?:first|top|limit|show)\s+(\d+)", r"(\d+)\s+(?:rows|records|entries)", r"limit\s+(\d+)"]:
        match = re.search(pattern, question_lower)
        if match:
            custom_limit = int(match.group(1))
            break

    is_large = wants_all or bool(custom_limit and custom_limit > 1000)

    if wants_all:
        return is_large, None, 300
    if custom_limit:
        if custom_limit > 10000:
            return is_large, custom_limit, 180
        if custom_limit > 5000:
            return is_large, custom_limit, 120
        if custom_limit > 1000:
            return is_large, custom_limit, 60
        return is_large, custom_limit, 30
    return is_large, 1000, 30


def generate_sql(
    question: str,
    table_name: str,
    columns_list: list[str] | None = None,
    custom_limit: int | None = None,
    llm_model: str = DEFAULT_LLM_MODEL,
) -> str:
    is_uploaded_table = table_name.startswith("uploaded_")
    columns_info = ""
    if columns_list:
        columns_info = f"\nAvailable columns: {', '.join(columns_list)}\nIMPORTANT: Only use these exact column names!"

    if custom_limit is None:
        limit_instruction = "DO NOT add any LIMIT clause - user wants all data"
    elif custom_limit > 1000:
        limit_instruction = f"Add LIMIT {custom_limit} to get the requested {custom_limit:,} rows"
    else:
        limit_instruction = f"Add LIMIT {custom_limit} for safety"

    if is_uploaded_table:
        prompt = f"""You are a SQL expert. Generate a single SQLite SQL query that precisely answers this question:

Question: {question}

Table: {table_name}{columns_info}

Rules:
- Return ONLY the raw SQL query — no explanation, no markdown, no code fences
- Use SQLite syntax (use LIMIT, not TOP)
- FILTERING: Always add a WHERE clause when the question mentions a specific name, value, category, or condition
- AGGREGATION: Use SUM(), COUNT(), AVG(), MIN(), MAX() with GROUP BY when the question asks for statistics, totals, summaries, or comparisons
- Do NOT return SELECT * when an aggregated or filtered result is clearly needed
- Only reference columns listed above{f' — add LIMIT {custom_limit} when returning individual rows (omit for single-row aggregates)' if custom_limit else ''}

SQL query:"""
    else:
        prompt = f"""
Generate SQL Server SQL for this question: {question}

Table: {table_name}{columns_info}
Rules:
- Use SQL Server T-SQL syntax
- {limit_instruction}
- Use fully qualified table names (schema.table)
- Only use columns that exist in the table
- Prefer summary queries (COUNT, SUM) over SELECT * when appropriate
- For simple row limiting use TOP
- For pagination use ORDER BY ... OFFSET ... FETCH NEXT
- NEVER use TOP and OFFSET in the same query

Return only SQL:"""

    response = get_llm(llm_model).invoke(prompt)

    # Record token usage if available
    if _cost_tracker is not None:
        try:
            usage = getattr(response, "usage_metadata", None) or {}
            input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
            output_tokens = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
            if input_tokens or output_tokens:
                _cost_tracker.record(llm_model, input_tokens, output_tokens, pipeline="text2sql")
        except Exception:
            pass

    return response.content.strip()
