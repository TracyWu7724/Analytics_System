"""Hybrid retrieval combining vector and keyword search."""

from __future__ import annotations

try:
    from ..rag_modeling import PreparedQuery, RetrievalResult
    from .keyword_retriever import KeywordRetriever
    from .reranker import Reranker
    from .vector_store import FaissVectorStore
except ImportError:
    from rag_modeling import PreparedQuery, RetrievalResult
    from keyword_retriever import KeywordRetriever
    from reranker import Reranker
    from vector_store import FaissVectorStore


class HybridRetriever:
    """Combine dense retrieval with lexical search, then rerank."""

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
        self.keyword_retriever = KeywordRetriever(self.vector_store.metadata)
        self.reranker = Reranker(reranker_model_name)

    @property
    def known_product_ids(self) -> set[str]:
        """
        Lowercased product identifiers known to the index.
        Combines product_id and source_file fields from every chunk's metadata
        so that either naming convention matches during Layer-1 product checks.
        """
        ids: set[str] = set()
        for m in self.vector_store.metadata:
            if m.get("product_id"):
                ids.add(m["product_id"].lower())
            if m.get("source_file"):
                ids.add(m["source_file"].lower())
        return ids

    def retrieve(
        self,
        query: str,
        initial_k: int = 10,
        final_k: int = 5,
        product_uuid: str | None = None,
    ) -> list[RetrievalResult]:
        vector_hits = (
            self.vector_store.search_within_product(product_uuid, query, k=initial_k)
            if product_uuid
            else self.vector_store.search(query, k=initial_k)
        )
        keyword_hits = self.keyword_retriever.search(query, k=initial_k, product_uuid=product_uuid)

        merged: dict[str, RetrievalResult] = {}
        for result in [*vector_hits, *keyword_hits]:
            key = result.metadata.get("id", result.text)
            current = merged.get(key)
            if current is None or result.score > current.score:
                merged[key] = result

        return self.reranker.rerank(query, list(merged.values()), top_k=final_k)

    def retrieve_for_prepared_query(
        self,
        prepared_query: PreparedQuery,
        initial_k: int = 10,
        final_k: int = 5,
        product_uuid: str | None = None,
    ) -> list[RetrievalResult]:
        merged: dict[str, RetrievalResult] = {}
        for query_variant in prepared_query.all_queries():
            for result in self.retrieve(query_variant, initial_k=initial_k, final_k=initial_k, product_uuid=product_uuid):
                key = result.metadata.get("id", result.text)
                current = merged.get(key)
                if current is None or result.score > current.score:
                    merged[key] = result
        # For comparative queries use the concept query for reranking so
        # alternative products rank above the reference product.
        rerank_q = prepared_query.rerank_query or prepared_query.rewritten
        return self.reranker.rerank(rerank_q, list(merged.values()), top_k=final_k)
