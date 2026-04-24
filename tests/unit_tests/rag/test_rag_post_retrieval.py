"""Unit tests for services.rag.retrieval.reranker (Reranker)."""

from unittest.mock import MagicMock, patch

import pytest

from services.rag.retrieval.reranker import Reranker
from services.rag.rag_modeling import RetrievalResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(text: str, score: float = 0.5, source: str = "vector") -> RetrievalResult:
    return RetrievalResult(text=text, score=score, metadata={"id": text}, source=source)


# ---------------------------------------------------------------------------
# Reranker (no model — lexical fallback)
# ---------------------------------------------------------------------------

class TestRerankerLexical:
    """Reranker with no model loaded falls back to SequenceMatcher scoring."""

    def setup_method(self):
        self.reranker = Reranker(model_name=None)

    def test_enabled_is_false_without_model(self):
        assert self.reranker.enabled is False

    def test_rerank_returns_top_k(self):
        candidates = [_result(f"chunk {i}") for i in range(6)]
        result = self.reranker.rerank("query", candidates, top_k=3)
        assert len(result) == 3

    def test_rerank_empty_candidates(self):
        assert self.reranker.rerank("query", [], top_k=3) == []

    def test_top_k_clamped_to_candidate_count(self):
        candidates = [_result("only one")]
        result = self.reranker.rerank("query", candidates, top_k=10)
        assert len(result) == 1

    def test_results_sorted_descending(self):
        candidates = [_result("text"), _result("text text text")]
        result = self.reranker.rerank("text", candidates, top_k=2)
        assert result[0].score >= result[1].score

    def test_source_label_updated(self):
        candidates = [_result("some text", source="vector")]
        result = self.reranker.rerank("some", candidates, top_k=1)
        assert "lexical_rerank" in result[0].source

    def test_lexical_score_is_float(self):
        score = Reranker._lexical_score("query", "this is a query test", base_score=0.4)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_exact_match_scores_high(self):
        score = Reranker._lexical_score("cure time", "cure time", base_score=0.0)
        high = Reranker._lexical_score("cure time", "unrelated irrelevant content", base_score=0.0)
        assert score > high

    def test_base_score_contributes(self):
        low = Reranker._lexical_score("text", "text", base_score=0.0)
        high = Reranker._lexical_score("text", "text", base_score=1.0)
        assert high > low


# ---------------------------------------------------------------------------
# Reranker with model (mocked)
# ---------------------------------------------------------------------------

class TestRerankerWithModel:
    def _make_reranker_with_mock_model(self):
        """Build a Reranker whose model/tokenizer are replaced with mocks."""
        reranker = Reranker.__new__(Reranker)
        reranker.model_name = "cross-encoder/ms-marco-MiniLM-L-6-v2"
        reranker.max_length = 512
        reranker.device = "cpu"

        import torch

        mock_tokenizer = MagicMock()
        encoded = MagicMock()
        encoded.to.return_value = encoded

        # tokenizer(...) returns encoded, model(**encoded).logits returns a tensor
        mock_tokenizer.return_value = encoded
        mock_model = MagicMock()
        mock_model.return_value.logits = torch.tensor([0.9, 0.1, 0.5])

        reranker.tokenizer = mock_tokenizer
        reranker.model = mock_model
        return reranker

    def test_enabled_is_true_with_model(self):
        reranker = self._make_reranker_with_mock_model()
        assert reranker.enabled is True

    def test_returns_top_k_sorted(self):
        reranker = self._make_reranker_with_mock_model()
        candidates = [_result(f"chunk {i}") for i in range(3)]

        result = reranker.rerank("query", candidates, top_k=2)
        assert len(result) == 2
        assert result[0].score >= result[1].score

    def test_source_label_updated_to_reranked(self):
        reranker = self._make_reranker_with_mock_model()
        candidates = [_result("text", source="vector")]

        # Patch _rerank_with_model to avoid torch inference complexity
        with patch.object(
            reranker,
            "_rerank_with_model",
            return_value=[_result("text", score=0.9, source="vector_reranked")],
        ):
            result = reranker.rerank("query", candidates, top_k=1)
        assert "reranked" in result[0].source
