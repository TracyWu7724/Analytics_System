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

try:
    from observability.metrics.costs import record_llm_usage
except Exception:
    record_llm_usage = None

from ..state import AgentState

# ── Schema-introspection fast path ──────────────────────────────────────────
# Detected before the LLM call to avoid wasted tokens and wrong routing.

import re as _re

_SCHEMA_PATTERNS = [
    r'\b(list|show|give|what|tell).{0,30}\b(table|tables|schema|dataset|datasets)\b',
    r'\b(available|existing|all)\b.{0,20}\b(table|tables|data)\b',
    r'\bwhat (data|tables?|datasets?).{0,20}\b(available|exist|have|do you have)\b',
    r'\bdata(base)? schema\b',
    r'\bdatabricks.{0,20}\btable\b',
    r'\bshow.{0,20}(all|every).{0,20}table\b',
    r'\blist.{0,20}(data|table)\b',
]
_SCHEMA_RE = _re.compile('|'.join(_SCHEMA_PATTERNS), _re.IGNORECASE)


def _is_schema_question(question: str) -> bool:
    return bool(_SCHEMA_RE.search(question))


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


def _clean_llm_output(raw: str) -> str:
    """Strip thinking blocks and markdown fences that small models emit."""
    # Remove <think>...</think> blocks (Qwen3 and other reasoning models)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    # Remove markdown code fences
    raw = re.sub(r"```(?:json)?\s*", "", raw)
    return raw.strip()


def _parse_route(raw: str, question: str) -> tuple[str, str]:
    """Extract (route, reasoning) from raw LLM output, with graceful fallbacks."""
    cleaned = _clean_llm_output(raw)

    # Try JSON first
    json_match = re.search(r"\{.*?\}", cleaned, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            route = str(parsed.get("route", "")).lower().strip()
            reasoning = parsed.get("reasoning", "")
            if route in ("sql", "rag", "both"):
                return route, reasoning
        except json.JSONDecodeError:
            pass

    # Fallback: look for a bare route word in the cleaned output
    for candidate in ("both", "rag", "sql"):  # order matters: most specific first
        if re.search(rf'\b{candidate}\b', cleaned, re.IGNORECASE):
            return candidate, "extracted from plain-text response"

    return _fallback_route(question), "keyword-based fallback"


def router_node(state: AgentState) -> dict:
    """LangGraph node: classify the question and set state["route"].

    Uses the user's chosen model for routing, falling back to keyword matching
    if the LLM call fails.
    """
    question = state["question"]
    user_model = state.get("llm_model", "gemini-2.5-flash")

    # Fast path: schema introspection questions bypass the LLM router entirely
    if _is_schema_question(question):
        return {"route": "schema", "route_reasoning": "Question asks for table/schema listing"}

    try:
        llm = get_llm(user_model)
        response = llm.invoke(_ROUTER_PROMPT.format(question=question))
        if record_llm_usage is not None:
            record_llm_usage(user_model, response, pipeline="router")
        route, reasoning = _parse_route(response.content, question)
        return {"route": route, "route_reasoning": reasoning}
    except Exception:
        pass

    # Model failed — use keyword heuristic
    return {
        "route": _fallback_route(question),
        "route_reasoning": "error in router — used keyword fallback",
    }


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
