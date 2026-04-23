"""Candidate reranking for RAG retrieval."""

from __future__ import annotations

from difflib import SequenceMatcher

try:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
except Exception:  # pragma: no cover
    torch = None
    AutoModelForSequenceClassification = None
    AutoTokenizer = None

try:
    from ..rag_modeling import RetrievalResult
except ImportError:
    from rag_modeling import RetrievalResult


class Reranker:
    """Rerank retrieval candidates with a cross-encoder or lexical fallback."""

    def __init__(self, model_name: str | None = None, max_length: int = 512):
        self.model_name = model_name
        self.max_length = max_length
        self.device = "cpu"
        self.tokenizer = None
        self.model = None

        if model_name and AutoTokenizer and AutoModelForSequenceClassification and torch:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self.model.to(self.device)
            self.model.eval()

    @property
    def enabled(self) -> bool:
        return self.model is not None and self.tokenizer is not None and torch is not None

    def rerank(self, query: str, candidates: list[RetrievalResult], top_k: int = 3) -> list[RetrievalResult]:
        """Return the best candidates ordered by descending relevance."""
        if not candidates:
            return []

        top_k = max(1, min(top_k, len(candidates)))
        if self.enabled:
            return self._rerank_with_model(query, candidates, top_k)
        return self._rerank_lexically(query, candidates, top_k)

    def _rerank_with_model(
        self,
        query: str,
        candidates: list[RetrievalResult],
        top_k: int,
    ) -> list[RetrievalResult]:
        assert self.tokenizer is not None and self.model is not None and torch is not None

        pairs = [[query, candidate.text] for candidate in candidates]
        encoded = self.tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        ).to(self.device)

        with torch.no_grad():
            scores = self.model(**encoded).logits.view(-1).float().cpu().tolist()

        reranked = [
            RetrievalResult(
                text=candidate.text,
                score=float(score),
                metadata=candidate.metadata,
                source=f"{candidate.source}_reranked",
            )
            for candidate, score in zip(candidates, scores)
        ]
        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked[:top_k]

    def _rerank_lexically(
        self,
        query: str,
        candidates: list[RetrievalResult],
        top_k: int,
    ) -> list[RetrievalResult]:
        reranked = [
            RetrievalResult(
                text=candidate.text,
                score=self._lexical_score(query, candidate.text, candidate.score),
                metadata=candidate.metadata,
                source=f"{candidate.source}_lexical_rerank",
            )
            for candidate in candidates
        ]
        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked[:top_k]

    @staticmethod
    def _lexical_score(query: str, text: str, base_score: float = 0.0) -> float:
        similarity = SequenceMatcher(None, query.lower(), text.lower()).ratio()
        return float((0.7 * similarity) + (0.3 * base_score))
