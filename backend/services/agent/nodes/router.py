"""
nodes/router.py — LLM-based router that decides which pipeline to invoke.

Routes the question to one of:
  "sql"  — structured data query (counts, sums, lists, comparisons from a database)
  "rag"  — knowledge/document question (specs, how-to, product info, explanations)
  "both" — needs data AND knowledge (e.g. "why did sales of LOCTITE 401 drop?")

The decision is written back to AgentState under the "route" key.
"""

from __future__ import annotations

import json
import re

try:
    from ....services.text2sql.generation.llm_registry import get_llm
except Exception:
    try:
        from backend.services.text2sql.generation.llm_registry import get_llm
    except Exception:
        from generation.llm_registry import get_llm

from ..state import AgentState

_ROUTER_PROMPT = """\
You are a routing agent for a Decision Support System.

Classify the user's question into one of three routes:

  "sql"  — The question asks for data, numbers, lists, or analysis from a structured database.
           Examples: "how many units sold last quarter", "show top 10 products by revenue",
                     "what is the average deal size", "list all orders in January"

  "rag"  — The question asks for knowledge, explanations, specs, or product documentation.
           Examples: "what is the cure time for LOCTITE 401", "how do I apply this adhesive",
                     "what are the safety precautions", "explain the viscosity specs"

  "both" — The question needs BOTH structured data AND product/document knowledge.
           Examples: "why did sales of LOCTITE 401 drop this quarter",
                     "what are the specs of our best-selling product",
                     "compare the performance of our top adhesives with their sales"

Respond with a JSON object only, no extra text:
{{"route": "sql"|"rag"|"both", "reasoning": "one sentence explaining why"}}

Question: {question}
"""


def router_node(state: AgentState) -> dict:
    """LangGraph node: classify the question and set state["route"]."""
    llm_model = state.get("llm_model", "gemini-2.5-flash")
    question = state["question"]

    try:
        llm = get_llm(llm_model)
        response = llm.invoke(_ROUTER_PROMPT.format(question=question))
        raw = response.content.strip()

        # Extract JSON even if LLM wraps it in markdown fences
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            route = parsed.get("route", "sql").lower()
            reasoning = parsed.get("reasoning", "")
        else:
            route, reasoning = _fallback_route(question), "keyword-based fallback"

        # Normalise to valid values
        if route not in ("sql", "rag", "both"):
            route = _fallback_route(question)

    except Exception:
        route = _fallback_route(question)
        reasoning = "error in router — used keyword fallback"

    return {"route": route, "route_reasoning": reasoning}


# ---------------------------------------------------------------------------
# Keyword fallback (used when LLM call fails)
# ---------------------------------------------------------------------------

_SQL_KEYWORDS = {
    "how many", "count", "sum", "total", "average", "avg", "list", "show",
    "top", "bottom", "rank", "sales", "revenue", "orders", "units",
    "which", "when", "where", "compare", "trend", "quarter", "month",
}

_RAG_KEYWORDS = {
    "what is", "how to", "how do", "explain", "describe", "spec",
    "cure time", "viscosity", "temperature", "sds", "tds", "safety",
    "adhesive", "loctite", "henkel", "product", "datasheet",
}


def _fallback_route(question: str) -> str:
    q = question.lower()
    sql_hits = sum(1 for kw in _SQL_KEYWORDS if kw in q)
    rag_hits = sum(1 for kw in _RAG_KEYWORDS if kw in q)
    if sql_hits > 0 and rag_hits > 0:
        return "both"
    if rag_hits > sql_hits:
        return "rag"
    return "sql"
