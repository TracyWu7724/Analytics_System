"""Lightweight lexical retrieval for RAG."""

from __future__ import annotations

import math
import re
from collections import Counter

try:
    from ..rag_modeling import RetrievalResult
except ImportError:
    from rag_modeling import RetrievalResult


class KeywordRetriever:
    """Simple BM25-style retriever without extra dependencies."""

    def __init__(self, corpus: list[dict]):
        self.corpus = corpus
        self.tokenized_docs = [self._tokenize(doc["text"]) for doc in corpus]
        self.doc_freq: Counter[str] = Counter()
        self.avg_doc_len = 0.0
        self._build_stats()

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"\b\w+\b", text.lower())

    def _build_stats(self):
        total_length = 0
        for tokens in self.tokenized_docs:
            total_length += len(tokens)
            for token in set(tokens):
                self.doc_freq[token] += 1
        self.avg_doc_len = total_length / max(len(self.tokenized_docs), 1)

    def _idf(self, token: str) -> float:
        n = len(self.tokenized_docs)
        df = self.doc_freq.get(token, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 5, product_uuid: str | None = None) -> list[RetrievalResult]:
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores: list[RetrievalResult] = []
        for doc, tokens in zip(self.corpus, self.tokenized_docs):
            if product_uuid and doc.get("product_uuid") != product_uuid:
                continue

            token_counts = Counter(tokens)
            score = 0.0
            doc_len = max(len(tokens), 1)
            for token in query_tokens:
                tf = token_counts.get(token, 0)
                if tf == 0:
                    continue
                idf = self._idf(token)
                score += idf * (tf * 2.2) / (tf + 1.2 * (1 - 0.75 + 0.75 * doc_len / max(self.avg_doc_len, 1)))

            if score > 0:
                scores.append(
                    RetrievalResult(
                        text=doc["text"],
                        score=float(score),
                        metadata=doc,
                        source="keyword",
                    )
                )

        scores.sort(key=lambda item: item.score, reverse=True)
        return scores[:k]
