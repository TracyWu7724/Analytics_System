"""
tools/rag_tool.py — thin wrapper around the v1 RAG pipeline.

Exposes run_rag() which takes a question + config and returns the answer
plus the retrieved chunks for transparency.
"""

from __future__ import annotations

import os
from typing import Optional

try:
    from ...rag.pre_retrieval.query_expansion import QueryExpander
    from ...rag.retrieval.hybrid_retriever import HybridRetriever
    from ...rag.generation.generation import ask_llm, build_prompt
    from ...rag.rag_modeling import RetrievalResult
except ImportError:
    from rag.pre_retrieval.query_expansion import QueryExpander
    from rag.retrieval.hybrid_retriever import HybridRetriever
    from backend.services.rag.generation.generation import ask_llm, build_prompt
    from rag.rag_modeling import RetrievalResult


def _infer_llm_origin(model_name: str) -> str:
    m = model_name.lower()
    if m.startswith("gemini"):
        return "Gemini"
    if m.startswith("gpt"):
        return "OpenAI"
    # Ollama-served models: gemma, qwen3
    return "Ollama"


def run_rag(
    question: str,
    metadata_path: str,
    faiss_path: str,
    *,
    embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    llm_origin: Optional[str] = None,
    llm_model: str = "gemini-2.5-flash",
    reranker_model_name: Optional[str] = None,
    initial_k: int = 10,
    final_k: int = 5,
    product_uuid: Optional[str] = None,
    history: Optional[list[dict]] = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    denied_sources: Optional[list[str]] = None,
) -> dict:
    """
    Run the full RAG pipeline and return answer + retrieved chunks.

    Returns
    -------
    {
        "answer": str,
        "chunks": [{"text": str, "score": float, "source": str, "metadata": dict}],
        "error": str | None,
    }
    """
    try:
        retriever = HybridRetriever(
            metadata_path=metadata_path,
            faiss_path=faiss_path,
            embed_model_name=embed_model_name,
            reranker_model_name=reranker_model_name,
        )
        expander = QueryExpander()
        prepared = expander.expand(question)

        results: list[RetrievalResult] = retriever.retrieve_for_prepared_query(
            prepared,
            initial_k=initial_k,
            final_k=final_k,
            product_uuid=product_uuid,
        )

        # Filter out denied sources BEFORE building the LLM context.
        # Match against product_id and source_file in metadata (r.source is the
        # retrieval method "vector"/"bm25", not the document identifier).
        if denied_sources:
            def _chunk_identifier(r: RetrievalResult) -> str:
                return (
                    r.metadata.get("product_id", "")
                    + "|"
                    + r.metadata.get("source_file", "")
                )

            results = [
                r for r in results
                if not any(pattern in _chunk_identifier(r) for pattern in denied_sources)
            ]

        chunks = [
            {
                "text": r.text,
                "score": r.score,
                "source": r.metadata.get("source_file") or r.metadata.get("product_id") or r.source,
                "metadata": r.metadata,
            }
            for r in results
        ]

        context = "\n\n".join(r.text for r in results)
        prompt = build_prompt(context=context, question=question, history=history)
        origin = llm_origin or _infer_llm_origin(llm_model)
        answer = ask_llm(
            prompt,
            llm_origin=origin,
            llm_model=llm_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return {"answer": answer, "chunks": chunks, "error": None}

    except Exception as e:
        return {"answer": "", "chunks": [], "error": str(e)}
