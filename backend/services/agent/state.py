"""
state.py — shared AgentState for the LangGraph decision agent.

Every node reads and writes this dict.  Fields are Optional so nodes can
be skipped cleanly when only one pipeline is needed.
"""

from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict):
    # ── Input ────────────────────────────────────────────────────────────────
    question: str
    history: list[dict]          # [{"role": "user"|"assistant", "content": "..."}]
    uploaded_table: Optional[str]  # if user has an uploaded CSV in context
    llm_model: str               # which LLM to use for generation

    # ── Auth / data-access ───────────────────────────────────────────────────
    denied_tables: Optional[list[str]]       # table name substrings the user cannot query
    denied_rag_sources: Optional[list[str]]  # RAG source substrings the user cannot see

    # ── Routing ──────────────────────────────────────────────────────────────
    route: Optional[str]         # "sql" | "rag" | "both"
    route_reasoning: Optional[str]  # why the router chose this route

    # ── SQL pipeline ─────────────────────────────────────────────────────────
    sql_table: Optional[str]
    sql_query: Optional[str]
    sql_rows: Optional[list[dict]]
    sql_error: Optional[str]
    sql_attempts: int            # self-correction retry counter

    # ── RAG pipeline ─────────────────────────────────────────────────────────
    rag_answer: Optional[str]
    rag_chunks: Optional[list[dict]]  # retrieved context chunks
    rag_error: Optional[str]

    # ── Output ───────────────────────────────────────────────────────────────
    final_answer: Optional[str]
    error: Optional[str]
