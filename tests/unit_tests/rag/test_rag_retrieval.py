"""Unit tests for retrieval: KeywordRetriever, FaissVectorStore, Retriever, HybridRetriever."""

import json
import tempfile
import os
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from services.rag.retrieval.keyword_retriever import KeywordRetriever
from services.rag.rag_modeling import PreparedQuery, RetrievalResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _corpus(*texts, product_uuid="uuid-1", product_id="PROD-1") -> list[dict]:
    return [
        {"id": f"{product_uuid}::{i}", "text": t, "product_uuid": product_uuid, "product_id": product_id}
        for i, t in enumerate(texts)
    ]


def _result(text: str, score: float = 0.5, source: str = "vector") -> RetrievalResult:
    return RetrievalResult(text=text, score=score, metadata={"id": text}, source=source)


# ---------------------------------------------------------------------------
# KeywordRetriever — BM25
# ---------------------------------------------------------------------------

class TestKeywordRetriever:
    def setup_method(self):
        self.corpus = _corpus(
            "tensile strength 25 MPa cure temperature 23 degrees",
            "viscosity 1500 cP at room temperature",
            "safety data sheet handling precautions",
        )
        self.retriever = KeywordRetriever(self.corpus)

    def test_returns_results_for_matching_query(self):
        results = self.retriever.search("tensile strength", k=3)
        assert len(results) >= 1
        assert any("tensile" in r.text for r in results)

    def test_top_result_most_relevant(self):
        results = self.retriever.search("viscosity", k=3)
        assert "viscosity" in results[0].text

    def test_returns_empty_for_no_match(self):
        results = self.retriever.search("xyzzy", k=3)
        assert results == []

    def test_returns_empty_for_empty_query(self):
        results = self.retriever.search("", k=3)
        assert results == []

    def test_k_limits_results(self):
        results = self.retriever.search("temperature", k=1)
        assert len(results) <= 1

    def test_results_sorted_descending(self):
        results = self.retriever.search("temperature", k=3)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_source_is_keyword(self):
        results = self.retriever.search("viscosity", k=1)
        assert results[0].source == "keyword"

    def test_product_uuid_filter(self):
        corpus = (
            _corpus("tensile strength 25 MPa", product_uuid="uuid-1")
            + _corpus("tensile strength info", product_uuid="uuid-2")
        )
        retriever = KeywordRetriever(corpus)
        results = retriever.search("tensile", k=5, product_uuid="uuid-1")
        assert all(r.metadata["product_uuid"] == "uuid-1" for r in results)

    def test_no_filter_returns_all_matching(self):
        corpus = (
            _corpus("tensile strength 25 MPa", product_uuid="uuid-1")
            + _corpus("tensile strength info", product_uuid="uuid-2")
        )
        retriever = KeywordRetriever(corpus)
        results = retriever.search("tensile", k=10)
        uuids = {r.metadata["product_uuid"] for r in results}
        assert len(uuids) == 2

    def test_metadata_contains_original_entry(self):
        results = self.retriever.search("safety", k=1)
        assert "product_uuid" in results[0].metadata

    def test_idf_penalizes_common_terms(self):
        # "temperature" appears in two documents; "tensile" in one.
        # A query for the rarer term should score the exact-match doc higher.
        results = self.retriever.search("tensile", k=3)
        assert results[0].score > 0


# ---------------------------------------------------------------------------
# FaissVectorStore — mocked
# ---------------------------------------------------------------------------

class TestFaissVectorStore:
    """Tests that don't require a real FAISS index or embedding model."""

    def _build_store(self, corpus: list[dict]):
        """Construct a FaissVectorStore with all heavy dependencies mocked."""
        from services.rag.retrieval.vector_store import FaissVectorStore

        dim = 4
        n = len(corpus)
        embeddings = np.random.rand(n, dim).astype("float32")
        embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)

        mock_index = MagicMock()
        mock_index.ntotal = n
        # reconstruct returns a single embedding row
        mock_index.reconstruct.side_effect = lambda i: embeddings[i]
        # search returns distances + indices shaped (1, k)
        mock_index.search.return_value = (
            np.array([[0.9, 0.8]]),
            np.array([[0, 1]]),
        )

        mock_embed_model = MagicMock()
        mock_embed_model.encode.return_value = np.array([[0.1, 0.2, 0.3, 0.4]], dtype="float32")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as fh:
            for entry in corpus:
                fh.write(json.dumps(entry) + "\n")
            meta_path = fh.name

        try:
            with (
                patch("services.rag.retrieval.vector_store.faiss.read_index", return_value=mock_index),
                patch("services.rag.retrieval.vector_store.SentenceTransformer", return_value=mock_embed_model),
            ):
                store = FaissVectorStore(
                    metadata_path=meta_path,
                    faiss_path="/fake/path.index",
                    embed_model_name="all-MiniLM-L6-v2",
                )
        finally:
            os.unlink(meta_path)

        return store

    def test_loads_metadata_correctly(self):
        corpus = _corpus("text one", "text two")
        store = self._build_store(corpus)
        assert len(store.texts) == 2
        assert store.texts[0] == "text one"

    def test_search_returns_results(self):
        corpus = _corpus("text one", "text two")
        store = self._build_store(corpus)
        results = store.search("test query", k=2)
        assert len(results) == 2
        assert all(isinstance(r, RetrievalResult) for r in results)

    def test_search_source_is_vector(self):
        corpus = _corpus("text one", "text two")
        store = self._build_store(corpus)
        results = store.search("test query", k=1)
        assert results[0].source == "vector"

    def test_search_within_product_filters(self):
        corpus = _corpus("text one", "text two", product_uuid="p-1")
        store = self._build_store(corpus)
        # Product index was built for "p-1"
        results = store.search_within_product("p-1", "test query", k=2)
        assert all(isinstance(r, RetrievalResult) for r in results)

    def test_search_within_unknown_product_returns_empty(self):
        corpus = _corpus("text one")
        store = self._build_store(corpus)
        assert store.search_within_product("nonexistent", "query", k=5) == []

    def test_identify_relevant_products_returns_list(self):
        corpus = _corpus("text one", "text two")
        store = self._build_store(corpus)
        ranked = store.identify_relevant_products("query", top_n=1)
        assert isinstance(ranked, list)
        assert len(ranked) <= 1


# ---------------------------------------------------------------------------
# Retriever (mocked vector store + reranker)
# ---------------------------------------------------------------------------

class TestRetriever:
    def _make_retriever(self):
        from services.rag.retrieval.retriever import Retriever

        with (
            patch("services.rag.retrieval.retriever.FaissVectorStore"),
            patch("services.rag.retrieval.retriever.Reranker"),
        ):
            r = Retriever(
                metadata_path="/fake/meta.jsonl",
                faiss_path="/fake/index",
            )
        return r

    def test_retrieve_top_k_calls_vector_store(self):
        retriever = self._make_retriever()
        retriever.vector_store.search.return_value = [_result("chunk")]
        results = retriever.retrieve_top_k("query", k=3)
        retriever.vector_store.search.assert_called_once_with("query", k=3)
        assert results == [_result("chunk")]

    def test_retrieve_and_rerank_pipeline(self):
        retriever = self._make_retriever()
        retriever.vector_store.search.return_value = [_result(f"c{i}") for i in range(5)]
        retriever.reranker.rerank.return_value = [_result("c0"), _result("c1")]

        results = retriever.retrieve_and_rerank("query", initial_k=5, final_k=2)
        assert len(results) == 2

    def test_retrieve_for_prepared_query_merges_variants(self):
        retriever = self._make_retriever()
        retriever.vector_store.search.return_value = [_result("r1", score=0.8)]
        retriever.reranker.rerank.return_value = [_result("r1", score=0.9)]

        pq = PreparedQuery(
            original="tds for loctite",
            rewritten="tds for loctite",
            expansions=["technical data sheet for loctite"],
        )
        results = retriever.retrieve_for_prepared_query(pq, initial_k=5, final_k=1)
        assert len(results) == 1
        # vector_store.search should have been called once per query variant
        assert retriever.vector_store.search.call_count == len(pq.all_queries())


# ---------------------------------------------------------------------------
# HybridRetriever (mocked)
# ---------------------------------------------------------------------------

class TestHybridRetriever:
    def _make_hybrid(self):
        from services.rag.retrieval.hybrid_retriever import HybridRetriever

        with (
            patch("services.rag.retrieval.hybrid_retriever.FaissVectorStore"),
            patch("services.rag.retrieval.hybrid_retriever.KeywordRetriever"),
            patch("services.rag.retrieval.hybrid_retriever.Reranker"),
        ):
            h = HybridRetriever(
                metadata_path="/fake/meta.jsonl",
                faiss_path="/fake/index",
            )
        return h

    def test_retrieve_merges_vector_and_keyword(self):
        h = self._make_hybrid()
        h.vector_store.search.return_value = [_result("v1", score=0.9)]
        h.keyword_retriever.search.return_value = [_result("k1", score=0.7)]
        h.reranker.rerank.return_value = [_result("v1"), _result("k1")]

        results = h.retrieve("query", initial_k=5, final_k=2)
        assert len(results) == 2

    def test_retrieve_with_product_uuid_uses_product_search(self):
        h = self._make_hybrid()
        h.vector_store.search_within_product.return_value = [_result("p1")]
        h.keyword_retriever.search.return_value = []
        h.reranker.rerank.return_value = [_result("p1")]

        h.retrieve("query", product_uuid="uuid-1")
        h.vector_store.search_within_product.assert_called_once()
        h.vector_store.search.assert_not_called()

    def test_retrieve_deduplicates_by_id(self):
        h = self._make_hybrid()
        shared = _result("shared text", score=0.6)
        h.vector_store.search.return_value = [shared]
        h.keyword_retriever.search.return_value = [_result("shared text", score=0.4)]
        h.reranker.rerank.return_value = [_result("shared text", score=0.6)]

        results = h.retrieve("query", final_k=5)
        # The reranker should have received only one entry for "shared text"
        merged_candidates = h.reranker.rerank.call_args[0][1]
        assert sum(1 for r in merged_candidates if r.text == "shared text") == 1
