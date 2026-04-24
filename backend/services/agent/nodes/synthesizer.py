"""
nodes/synthesizer.py — merges SQL data + RAG knowledge into one answer.

Only invoked when route == "both".  The LLM receives the SQL result table
and the RAG-generated answer as context, then writes a unified response.
"""

from __future__ import annotations

import json

try:
    from ....services.text2sql.generation.llm_registry import get_llm
except Exception:
    try:
        from backend.services.text2sql.generation.llm_registry import get_llm
    except Exception:
        from generation.llm_registry import get_llm

from ..state import AgentState

_SYNTHESIZE_PROMPT = """\
You are a senior analyst. Combine the following two sources of information to \
answer the user's question in a clear, concise paragraph.

User question: {question}

--- Structured data (from database query) ---
SQL: {sql_query}
Results ({row_count} rows):
{sql_summary}

--- Product/document knowledge (from RAG) ---
{rag_answer}

Write a unified answer that uses both sources. Be specific and cite numbers \
from the data where relevant.
"""

_MAX_ROWS_IN_PROMPT = 10


def synthesizer_node(state: AgentState) -> dict:
    """LangGraph node: synthesize SQL data and RAG knowledge into final_answer."""
    question = state["question"]
    llm_model = state.get("llm_model", "gemini-2.5-flash")

    sql_rows = state.get("sql_rows") or []
    sql_query = state.get("sql_query", "")
    rag_answer = state.get("rag_answer", "")

    # If one pipeline failed, fall back to the other
    if not sql_rows and not rag_answer:
        error = state.get("sql_error") or state.get("rag_error") or "Both pipelines returned no results."
        return {"final_answer": f"I was unable to answer your question. {error}", "error": error}

    if not sql_rows:
        return {"final_answer": rag_answer, "error": None}

    if not rag_answer:
        summary = _format_rows(sql_rows)
        return {
            "final_answer": f"Here are the results:\n\n{summary}",
            "error": None,
        }

    # Both available — ask LLM to synthesise
    sql_summary = _format_rows(sql_rows[:_MAX_ROWS_IN_PROMPT])
    if len(sql_rows) > _MAX_ROWS_IN_PROMPT:
        sql_summary += f"\n... ({len(sql_rows) - _MAX_ROWS_IN_PROMPT} more rows)"

    prompt = _SYNTHESIZE_PROMPT.format(
        question=question,
        sql_query=sql_query,
        row_count=len(sql_rows),
        sql_summary=sql_summary,
        rag_answer=rag_answer,
    )

    try:
        llm = get_llm(llm_model)
        response = llm.invoke(prompt)
        answer = response.content.strip()
    except Exception as e:
        # Fallback: concatenate both answers
        answer = f"{rag_answer}\n\n**Data:**\n{_format_rows(sql_rows[:_MAX_ROWS_IN_PROMPT])}"

    return {"final_answer": answer, "error": None}


def _format_rows(rows: list[dict]) -> str:
    if not rows:
        return "(no data)"
    headers = list(rows[0].keys())
    lines = [" | ".join(headers)]
    lines.append("-" * len(lines[0]))
    for row in rows:
        lines.append(" | ".join(str(row.get(h, "")) for h in headers))
    return "\n".join(lines)
