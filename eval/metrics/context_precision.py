"""Contextual precision metric for RAG evaluation.

Contextual precision asks: "Of the chunks the retriever returned, how many
of the relevant ones were ranked at the top?"

Formula (weighted precision, same as WrenAI):
    score = (1 / |relevant retrieved|) * Σ_{k=1}^{n} precision@k * rel(k)

where rel(k) = 1 if retrieval_context[k-1] is in context, else 0.
"""

import asyncio

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase


class ContextualPrecisionMetric(BaseMetric):
    def __init__(self):
        self.threshold = 0
        self.score = 0

    def measure(self, test_case: LLMTestCase):
        return asyncio.run(self.a_measure(test_case))

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs):
        context = test_case.context or []
        retrieval_context = test_case.retrieval_context or []

        context_set = set(context)
        intersection = context_set & set(retrieval_context)
        intersection_count = len(intersection)

        if intersection_count == 0:
            self.score = 0.0
            self.success = False
            return self.score

        n = len(retrieval_context)
        summation = 0.0
        for k in range(1, n + 1):
            # precision@k: how many of the first k retrieved are relevant
            relevant_up_to_k = len(context_set & set(retrieval_context[:k]))
            precision_at_k = relevant_up_to_k / k
            # rel(k): is the k-th retrieved item itself relevant?
            rel_k = 1 if retrieval_context[k - 1] in context_set else 0
            summation += precision_at_k * rel_k

        self.score = (1 / intersection_count) * summation

        self.success = self.score >= self.threshold
        return self.score

    def is_successful(self):
        return self.success

    @property
    def __name__(self):
        return "ContextualPrecision(chunk-based)"
