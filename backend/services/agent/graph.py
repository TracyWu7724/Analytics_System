"""
graph.py — LangGraph StateGraph for the combined Text2SQL + RAG agent.

Graph topology
--------------

              ┌─────────┐
    START ──► │  router  │
              └────┬────┘
         ┌─────────┼──────────┐
        sql       rag        both
         │         │           │
         ▼         ▼           ▼
      sql_node  rag_node    sql_node ──► rag_node
         │         │                        │
    ┌────┴────┐    └────────────────────────┤
    │  error? │                             │
    │ retry ◄─┘                             ▼
    │                                  synthesizer
    └──► END                               │
                                          END

- sql_node has an internal self-correction loop (up to 3 attempts).
- "both" runs sql_node first, then rag_node, then synthesizer.
- For "sql" or "rag" only routes, final_answer is set inline by the
  respective end-node helper before reaching END.

Usage
-----
    from backend.services.agent.graph import build_agent

    agent = build_agent(
        data_service=data_service,
        metadata_path="...",
        faiss_path="...",
    )

    result = agent.invoke({
        "question": "why did LOCTITE 401 sales drop last quarter?",
        "history": [],
        "llm_model": "gemini-2.5-flash",
        "uploaded_table": None,
        "sql_attempts": 0,
    })
"""

from __future__ import annotations

import functools
from typing import Optional

from langgraph.graph import END, StateGraph

from .nodes.rag_node import rag_node, should_continue_after_rag
from .nodes.router import router_node
from .nodes.sql_node import should_retry_sql, sql_node
from .nodes.synthesizer import synthesizer_node
from .state import AgentState


def _set_final_answer_from_sql(state: AgentState) -> dict:
    """
    Terminal helper for sql-only route: format rows into final_answer.
    Called as the "end_sql" node so there is always a final_answer.
    """
    rows = state.get("sql_rows") or []
    error = state.get("sql_error")
    sql = state.get("sql_query", "")

    if error and not rows:
        return {"final_answer": f"SQL query failed after retries: {error}", "error": error}

    if not rows:
        return {"final_answer": "The query ran successfully but returned no results.", "error": None}

    # Build a readable summary (first 20 rows)
    headers = list(rows[0].keys())
    lines = [" | ".join(headers), "-" * max(len(h) for h in headers) * 2]
    for row in rows[:20]:
        lines.append(" | ".join(str(row.get(h, "")) for h in headers))
    if len(rows) > 20:
        lines.append(f"... ({len(rows) - 20} more rows)")
    table_str = "\n".join(lines)

    return {
        "final_answer": f"**SQL:** `{sql}`\n\n**Results ({len(rows)} rows):**\n{table_str}",
        "error": None,
    }


def _set_final_answer_from_rag(state: AgentState) -> dict:
    """Terminal helper for rag-only route."""
    answer = state.get("rag_answer")
    error = state.get("rag_error")
    if not answer:
        return {"final_answer": f"RAG pipeline returned no answer. {error or ''}", "error": error}
    return {"final_answer": answer, "error": None}


def build_agent(
    data_service,
    metadata_path: str = "",
    faiss_path: str = "",
    embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    reranker_model_name: Optional[str] = None,
    llm_origin: str = "Gemini",
    initial_k: int = 10,
    final_k: int = 5,
):
    """
    Compile and return the LangGraph agent.

    Parameters are injected into nodes via functools.partial so the graph
    remains a pure function of AgentState.
    """
    # Bind runtime dependencies into node functions
    _sql = functools.partial(sql_node, data_service=data_service)
    _rag = functools.partial(
        rag_node,
        metadata_path=metadata_path,
        faiss_path=faiss_path,
        embed_model_name=embed_model_name,
        reranker_model_name=reranker_model_name,
        llm_origin=llm_origin,
        initial_k=initial_k,
        final_k=final_k,
    )

    # ── Build graph ──────────────────────────────────────────────────────────
    graph = StateGraph(AgentState)

    graph.add_node("router", router_node)
    graph.add_node("sql_node", _sql)
    graph.add_node("rag_node", _rag)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("end_sql", _set_final_answer_from_sql)
    graph.add_node("end_rag", _set_final_answer_from_rag)

    # Entry point
    graph.set_entry_point("router")

    # Router → first node based on route
    graph.add_conditional_edges(
        "router",
        lambda s: s.get("route", "sql"),
        {
            "sql": "sql_node",
            "rag": "rag_node",
            "both": "sql_node",
        },
    )

    # SQL node → retry | rag | synthesizer | end_sql
    graph.add_conditional_edges(
        "sql_node",
        should_retry_sql,
        {
            "retry_sql": "sql_node",
            "rag_node": "rag_node",
            "synthesizer": "synthesizer",
            "end": "end_sql",
        },
    )

    # RAG node → synthesizer | sql_node | end_rag
    graph.add_conditional_edges(
        "rag_node",
        should_continue_after_rag,
        {
            "synthesizer": "synthesizer",
            "sql_node": "sql_node",
            "end": "end_rag",
        },
    )

    graph.add_edge("synthesizer", END)
    graph.add_edge("end_sql", END)
    graph.add_edge("end_rag", END)

    return graph.compile()
