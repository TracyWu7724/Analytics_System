"""
nodes/synthesizer.py — Hybrid synthesis of SQL data + RAG knowledge.

Only invoked when route == "both".

Hybrid framing
--------------
The two pipelines answer fundamentally different aspects of the question:

  Text2SQL  → quantitative facts from structured data
              (numbers, aggregates, comparisons, trends)

  RAG       → contextual knowledge from product documentation
              (specs, explanations, use-cases, root causes)

The synthesizer's job is to combine both into a single answer where the
numbers from the database are *explained* or *contextualised* by the
product knowledge — not just concatenated.

Degraded modes
--------------
  SQL only   → structured answer with no doc context
  RAG only   → doc answer with a clear note that no data was found
  Neither    → error message
"""

from __future__ import annotations

try:
    from ....services.text2sql.generation.llm_registry import get_llm
except Exception:
    try:
        from backend.services.text2sql.generation.llm_registry import get_llm
    except Exception:
        from generation.llm_registry import get_llm

try:
    from observability.metrics.costs import record_llm_usage
except Exception:
    record_llm_usage = None

from ..state import AgentState

# ── Prompt ────────────────────────────────────────────────────────────────────

_HYBRID_PROMPT = """\
You are a decision-support analyst combining two complementary data sources \
to answer a business question.

USER QUESTION
{question}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOURCE 1 — STRUCTURED DATA  (Text2SQL)
Quantitative facts retrieved directly from the database.
SQL executed: {sql_query}
Rows returned: {row_count}
{sql_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOURCE 2 — PRODUCT / DOCUMENT KNOWLEDGE  (RAG)
Contextual knowledge retrieved from product documentation.
{rag_answer}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSTRUCTIONS
Write a single, cohesive hybrid answer that:
1. Leads with the key quantitative finding from Source 1 (cite exact numbers).
2. Uses Source 2 to explain, contextualise, or give the "why" behind those numbers.
3. Connects the two explicitly — e.g. "The data shows X, which aligns with the \
product specification that states Y."
4. If Source 2 does not contain information relevant to the question, say so \
briefly and rely on the data.
5. Do NOT repeat the raw SQL or table dump. Summarise the data in prose.
6. Be concise — aim for 3–5 sentences unless the question requires more detail.
"""

_MAX_ROWS_IN_PROMPT = 10

# Phrases that indicate the RAG answer is itself empty / unhelpful.
# When SQL is also empty and the RAG answer matches one of these patterns,
# combining them produces a doubly-useless response — we return a clean
# refusal instead.
_RAG_EMPTY_PHRASES = [
    "does not provide information",
    "no information",
    "not provided in the context",
    "context does not",
    "documentation does not",
    "not available in",
    "cannot find",
    "no relevant information",
    "unable to find",
    "not mentioned",
    "no data",
]


def _rag_is_substantive(rag_answer: str) -> bool:
    """Return False only when the entire RAG answer is a refusal with no useful content.

    A mixed answer like "the docs don't cover revenue, but the product is used for..."
    is still substantive — we check length as a signal that real content exists
    alongside any refusal phrase.
    """
    if not rag_answer or not rag_answer.strip():
        return False
    lower = rag_answer.lower()
    has_refusal = any(phrase in lower for phrase in _RAG_EMPTY_PHRASES)
    if not has_refusal:
        return True
    # If the answer is long despite containing a refusal phrase it likely has
    # useful content too (e.g. "docs don't cover revenue, but usage is ...").
    return len(rag_answer.strip()) > 200


# ── Node ─────────────────────────────────────────────────────────────────────

def synthesizer_node(state: AgentState) -> dict:
    """LangGraph node: produce a hybrid answer from SQL data + RAG knowledge."""
    question  = state["question"]
    llm_model = state.get("llm_model", "gemini-2.5-flash")

    sql_rows   = state.get("sql_rows") or []
    sql_query  = state.get("sql_query") or ""
    rag_answer = state.get("rag_answer") or ""
    sql_error  = state.get("sql_error")
    rag_error  = state.get("rag_error")

    rag_useful = _rag_is_substantive(rag_answer)

    # ── Degraded: both pipelines returned nothing useful ─────────────────────
    if not sql_rows and not rag_useful:
        if sql_error:
            msg = (
                f"I was unable to retrieve data for your question. "
                f"The database query failed: {sql_error}"
            )
        else:
            msg = (
                "I was unable to find an answer. "
                "No matching records were found in the database, and the "
                "product documentation does not contain relevant information "
                "for this question. "
                "If you're asking about a sales or financial metric (e.g. profit, "
                "revenue), please ensure the product index is up to date and the "
                "product name matches what is stored in the database."
            )
        return {"final_answer": msg, "error": None}

    # ── Degraded: SQL found nothing but RAG has useful context ───────────────
    if not sql_rows:
        if sql_error:
            note = f"**Note:** The database query failed — {sql_error}\n\n"
        else:
            note = (
                "**Note:** No matching database records were found. "
                "The answer below is based on product documentation only.\n\n"
            )
        return {"final_answer": note + rag_answer, "error": None}

    # ── Degraded: RAG found nothing ──────────────────────────────────────────
    if not rag_answer:
        return {
            "final_answer": (
                "**Data results:**\n\n" + _format_rows(sql_rows) +
                "\n\n*No additional context was found in the product documentation.*"
            ),
            "error": None,
        }

    # ── Full hybrid synthesis ─────────────────────────────────────────────────
    sql_summary = _format_rows(sql_rows[:_MAX_ROWS_IN_PROMPT])
    if len(sql_rows) > _MAX_ROWS_IN_PROMPT:
        sql_summary += f"\n… ({len(sql_rows) - _MAX_ROWS_IN_PROMPT} more rows not shown)"

    prompt = _HYBRID_PROMPT.format(
        question=question,
        sql_query=sql_query,
        row_count=len(sql_rows),
        sql_summary=sql_summary,
        rag_answer=rag_answer,
    )

    try:
        llm = get_llm(llm_model)
        response = llm.invoke(prompt)
        if record_llm_usage is not None:
            record_llm_usage(llm_model, response, pipeline="synthesis")
        answer = response.content.strip()
    except Exception:
        # Fallback: structured concatenation so the user always gets something
        answer = (
            f"{rag_answer}\n\n"
            f"**Database results ({len(sql_rows)} rows):**\n"
            f"{_format_rows(sql_rows[:_MAX_ROWS_IN_PROMPT])}"
        )

    return {"final_answer": answer, "error": None}


# ── Formatting helper ─────────────────────────────────────────────────────────

def _format_rows(rows: list[dict]) -> str:
    if not rows:
        return "(no data)"
    headers = list(rows[0].keys())
    lines   = [" | ".join(headers), "-" * (len(" | ".join(headers)))]
    for row in rows:
        lines.append(" | ".join(str(row.get(h, "")) for h in headers))
    return "\n".join(lines)
