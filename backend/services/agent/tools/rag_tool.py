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
    from ...rag.rag_verifier import (
        verify_product_exists,
        verify_retrieval_quality,
        verify_answer_grounding,
    )
except ImportError:
    from rag.pre_retrieval.query_expansion import QueryExpander
    from rag.retrieval.hybrid_retriever import HybridRetriever
    from backend.services.rag.generation.generation import ask_llm, build_prompt
    from rag.rag_modeling import RetrievalResult
    from backend.services.rag.rag_verifier import (
        verify_product_exists,
        verify_retrieval_quality,
        verify_answer_grounding,
    )


# ── Retriever cache ───────────────────────────────────────────────────────────
# Loading the FAISS index from disk is expensive. Cache one HybridRetriever
# per unique (metadata_path, faiss_path, embed_model, reranker) combination so
# repeated calls within the same process reuse the loaded index.
_retriever_cache: dict[tuple, HybridRetriever] = {}


def _get_retriever(
    metadata_path: str,
    faiss_path: str,
    embed_model_name: str,
    reranker_model_name: Optional[str],
) -> HybridRetriever:
    key = (metadata_path, faiss_path, embed_model_name, reranker_model_name)
    if key not in _retriever_cache:
        _retriever_cache[key] = HybridRetriever(
            metadata_path=metadata_path,
            faiss_path=faiss_path,
            embed_model_name=embed_model_name,
            reranker_model_name=reranker_model_name,
        )
    return _retriever_cache[key]


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
    product_index=None,
    retrieval_question: Optional[str] = None,
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
        retriever = _get_retriever(
            metadata_path=metadata_path,
            faiss_path=faiss_path,
            embed_model_name=embed_model_name,
            reranker_model_name=reranker_model_name,
        )
        expander = QueryExpander(known_terms=retriever.known_product_ids)
        # Use retrieval_question (clean original) for retrieval/expansion so that
        # any hybrid-mode scoping notes appended to question don't pollute FAISS search.
        retrieval_q = retrieval_question or question
        prepared = expander.expand(retrieval_q)

        # ── Gate 1: Product exists in index? (pre-retrieval) ─────────────────
        # Use the spell-corrected query so that misspellings like "LOCYITE 243"
        # are resolved to "loctite 243" before product-existence is checked.
        gate1 = verify_product_exists(prepared.rewritten, retriever.known_product_ids, product_index=product_index)
        if not gate1.passed:
            return {
                "answer": gate1.refusal,
                "chunks": [],
                "error": None,
                "verification": {
                    "passed": False,
                    "failed_layer": 1,
                    "detail": gate1.detail,
                },
            }

        # ── Retrieval ─────────────────────────────────────────────────────────
        results: list[RetrievalResult] = retriever.retrieve_for_prepared_query(
            prepared,
            initial_k=initial_k,
            final_k=final_k,
            product_uuid=product_uuid,
        )

        # Filter denied sources BEFORE building the LLM context.
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
                "text":     r.text,
                "score":    r.score,
                "source":   r.metadata.get("source_file") or r.metadata.get("product_id") or r.source,
                "metadata": r.metadata,
            }
            for r in results
        ]

        # ── Gate 2: Relevant datasheet retrieved? (post-retrieval) ───────────
        gate2 = verify_retrieval_quality(question, chunks)
        if not gate2.passed:
            return {
                "answer": gate2.refusal,
                "chunks": chunks,
                "error": None,
                "verification": {
                    "passed": False,
                    "failed_layer": 2,
                    "detail": gate2.detail,
                },
            }

        # ── Generation ────────────────────────────────────────────────────────
        # Prepend product name to each chunk so the LLM knows which product
        # a property belongs to — critical for discovery queries like
        # "which products are medium-strength threadlockers?"
        def _chunk_header(r) -> str:
            pid = r.metadata.get("product_id") or r.metadata.get("source_file") or ""
            return f"[Product: {pid}]\n" if pid else ""

        context = "\n\n".join(_chunk_header(r) + r.text for r in results)
        prompt  = build_prompt(context=context, question=question, history=history)
        origin  = llm_origin or _infer_llm_origin(llm_model)
        answer  = ask_llm(
            prompt,
            llm_origin=origin,
            llm_model=llm_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # ── Gate 3: Answer supported by retrieved evidence? (post-generation) ─
        gate3 = verify_answer_grounding(answer, chunks)
        if not gate3.passed:
            answer = gate3.refusal + answer

        verification = {
            "passed":       gate3.passed,
            "failed_layer": 0 if gate3.passed else 3,
            "layers": [
                {"layer": g.layer, "name": g.name, "passed": g.passed,
                 "score": round(g.score, 3), "detail": g.detail}
                for g in (gate1, gate2, gate3)
            ],
        }

        return {"answer": answer, "chunks": chunks, "error": None, "verification": verification}

    except Exception as e:
        return {"answer": "", "chunks": [], "error": str(e), "verification": None}
