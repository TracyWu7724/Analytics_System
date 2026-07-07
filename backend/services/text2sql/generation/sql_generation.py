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
    history: list[dict] | None = None,
    product_hints: dict[str, str] | None = None,
    extra_tables: dict[str, list[str]] | None = None,
    mdl_context: str | None = None,
) -> str:
    # Build schema block — single table or multi-table
    if extra_tables:
        schema_lines = [f"Table: {table_name}"]
        if columns_list:
            schema_lines.append(f"  Columns: {', '.join(columns_list)}")
        for tname, cols in extra_tables.items():
            schema_lines.append(f"\nTable: {tname}")
            schema_lines.append(f"  Columns: {', '.join(cols)}")
        columns_info = "\n" + "\n".join(schema_lines) + "\nIMPORTANT: Only use column names listed above. JOIN tables using shared key columns."
    elif columns_list:
        columns_info = f"\nAvailable columns: {', '.join(columns_list)}\nIMPORTANT: Only use these exact column names!"
    else:
        columns_info = ""

    if custom_limit is None:
        limit_instruction = "DO NOT add any LIMIT clause — user wants all data"
    elif custom_limit > 1000:
        limit_instruction = f"Add LIMIT {custom_limit} to get the requested {custom_limit:,} rows"
    else:
        limit_instruction = f"Add LIMIT {custom_limit} for safety"

    history_block = ""
    if history:
        lines = []
        for msg in history[-6:]:   # last 3 turns (user + assistant pairs)
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role and content:
                lines.append(f"{role.capitalize()}: {content}")
        if lines:
            history_block = "Conversation history (use this to resolve pronouns and references):\n" + "\n".join(lines) + "\n\n"

    product_hints_block = ""
    if product_hints:
        lines = [f"  '{k}' → use '{v}' in WHERE clauses" for k, v in product_hints.items()]
        product_hints_block = (
            "Product name lookup (exact names as stored in the database — "
            "always use the right-hand value verbatim in WHERE clauses):\n"
            + "\n".join(lines) + "\n\n"
        )

    mdl_block = f"\n{mdl_context}\n" if mdl_context else ""

    prompt = f"""You are a Databricks SQL expert. Generate a single Databricks SQL query that precisely answers this question:

{history_block}{product_hints_block}{mdl_block}Question: {question}

Table: {table_name}{columns_info}

Rules:
- Return ONLY the raw SQL query — no explanation, no markdown, no code fences
- Use Databricks SQL syntax (Apache Spark SQL)
- CRITICAL: The FROM clause MUST use the EXACT table name: {table_name}
  Write it as: FROM {table_name} — never truncate or alter this name
- Do NOT wrap any part of the table name in brackets or quotes
- Use backticks only if a column name contains spaces or special characters
- {limit_instruction}
- Only reference columns listed above
- FILTERING: Add a WHERE clause only for specific named values, conditions, or date ranges. For brand/category mentions, use LOWER(column) LIKE LOWER('%value%') for case-insensitive matching — Databricks LIKE is case-sensitive. Never invent specific product names or use IN (...) with values not explicitly stated in the question. For ranking/aggregate questions ("top N", "best", "most"), do NOT add category filters unless the category value is explicitly stated — just ORDER BY the metric DESC
- COLUMN SELECTION FOR BRAND FILTERS: When the question mentions a brand name (a proper noun like "Loctite", "3M", "Henkel"), filter on the item/product name column (e.g. item_name, product_name, product, description) — NOT on a category column. Category words ("adhesives", "threadlockers", "sealants") belong in category columns. Brand names live in item name columns.
- AGGREGATION: Use SUM(), COUNT(), AVG(), MIN(), MAX() with GROUP BY when the question asks for statistics, totals, or comparisons
- INVENTORY/STOCK THRESHOLD: When the question asks which items have inventory/stock above or below a threshold (e.g. "below 100 units"), first aggregate stock with SUM() GROUP BY item, then apply the threshold in a HAVING clause — do NOT apply the threshold as a raw WHERE filter on a single row. Example pattern: SELECT item_name, SUM(stock_col) AS total_stock FROM ... WHERE <brand_filter> GROUP BY item_name HAVING SUM(stock_col) < 100
- DERIVED METRICS: If the question asks for profit, margin, growth, net revenue, or any metric that has no direct column, compute it from the available columns (e.g. margin = profit / revenue * 100). Never return SELECT * when a calculation is clearly needed. IMPORTANT: if the available columns include a direct "Revenue" or "Profit" column, use it directly — do NOT derive it from budget or cost columns on a different table
- Do NOT use TOP — use LIMIT instead
- Do NOT use square brackets [ ] — this is not SQL Server

SQL query:"""

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
