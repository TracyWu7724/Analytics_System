"""
nodes/rag_node.py — RAG pipeline node.

Runs hybrid retrieval + reranking + LLM generation via the v1 RAG tool.
Writes rag_answer and rag_chunks into AgentState.
"""

from __future__ import annotations

import os
from typing import Optional

from ..state import AgentState
from ..tools.rag_tool import run_rag


def rag_node(
    state: AgentState,
    *,
    metadata_path: str,
    faiss_path: str,
    embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    reranker_model_name: Optional[str] = None,
    llm_origin: str = "Gemini",
    initial_k: int = 10,
    final_k: int = 5,
) -> dict:
    """
    LangGraph node: run the RAG pipeline.

    Parameters injected at graph-build time via functools.partial.
    """
    question = state["question"]
    llm_model = state.get("llm_model", "gemini-2.5-flash")
    history = state.get("history") or []

    result = run_rag(
        question,
        metadata_path=metadata_path,
        faiss_path=faiss_path,
        embed_model_name=embed_model_name,
        llm_origin=llm_origin,
        llm_model=llm_model,
        reranker_model_name=reranker_model_name,
        initial_k=initial_k,
        final_k=final_k,
        history=history,
    )

    return {
        "rag_answer": result["answer"] or None,
        "rag_chunks": result["chunks"],
        "rag_error": result["error"],
    }


def should_continue_after_rag(state: AgentState) -> str:
    """
    Conditional edge after rag_node.

    Returns
    -------
    "synthesizer" — route is "both" and SQL already ran → synthesize
    "sql_node"    — route is "both" and SQL hasn't run yet
    "end"         — route is "rag" only
    """
    route = state.get("route", "rag")

    if route == "both":
        if state.get("sql_rows") is not None or state.get("sql_error"):
            return "synthesizer"
        return "sql_node"

    return "end"
