"""Main retrieval service aligned with the FAISS RAG reference."""

from __future__ import annotations

try:
    from ..rag_modeling import PreparedQuery, RetrievalResult
    from .reranker import Reranker
    from .vector_store import FaissVectorStore
except ImportError:
    from rag_modeling import PreparedQuery, RetrievalResult
    from reranker import Reranker
    from vector_store import FaissVectorStore


class Retriever:
    """Vector-first retriever with optional reranking and product-aware search."""

    def __init__(
        self,
        metadata_path: str,
        faiss_path: str,
        embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        reranker_model_name: str | None = None,
        trust_remote_code: bool = False,
    ):
        self.vector_store = FaissVectorStore(
            metadata_path=metadata_path,
            faiss_path=faiss_path,
            embed_model_name=embed_model_name,
            trust_remote_code=trust_remote_code,
        )
        self.reranker = Reranker(reranker_model_name)

    def retrieve_top_k(self, query: str, k: int = 3) -> list[RetrievalResult]:
        return self.vector_store.search(query, k=k)

    def retrieve_and_rerank(self, query: str, initial_k: int = 10, final_k: int = 3) -> list[RetrievalResult]:
        candidates = self.vector_store.search(query, k=initial_k)
        return self.reranker.rerank(query, candidates, top_k=final_k)

    def identify_relevant_products(self, query: str, top_n: int = 3) -> list[tuple[str, str, float]]:
        return self.vector_store.identify_relevant_products(query, top_n=top_n)

    def search_within_product(self, product_uuid: str, query: str, k: int = 5) -> list[RetrievalResult]:
        return self.vector_store.search_within_product(product_uuid, query, k=k)

    def retrieve_and_rerank_by_product(
        self,
        product_uuid: str,
        query: str,
        initial_k: int = 10,
        final_k: int = 3,
    ) -> list[RetrievalResult]:
        candidates = self.vector_store.search_within_product(product_uuid, query, k=initial_k)
        return self.reranker.rerank(query, candidates, top_k=final_k)

    def retrieve_for_prepared_query(
        self,
        prepared_query: PreparedQuery,
        initial_k: int = 10,
        final_k: int = 3,
    ) -> list[RetrievalResult]:
        merged: dict[str, RetrievalResult] = {}
        for query_variant in prepared_query.all_queries():
            for result in self.vector_store.search(query_variant, k=initial_k):
                key = result.metadata.get("id", result.text)
                current = merged.get(key)
                if current is None or result.score > current.score:
                    merged[key] = result
        return self.reranker.rerank(prepared_query.rewritten, list(merged.values()), top_k=final_k)
