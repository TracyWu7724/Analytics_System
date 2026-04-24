"""Contextual relevancy metric for RAG evaluation.

Identical semantics to WrenAI's version — no SQL-specific logic was needed
here because the formula already operates directly on context and
retrieval_context lists.

Measures what fraction of retrieved chunks are actually relevant (present in
the ideal context). This is recall from the retriever's perspective:
"How signal-dense is the retrieved set?"

Formula:
    score = |retrieval_context ∩ context| / |retrieval_context|
"""

import asyncio

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase


class ContextualRelevancyMetric(BaseMetric):
    def __init__(self):
        self.threshold = 0
        self.score = 0

    def measure(self, test_case: LLMTestCase):
        return asyncio.run(self.a_measure(test_case))

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs):
        context = test_case.context or []
        retrieval_context = test_case.retrieval_context or []

        if not retrieval_context:
            self.score = 0.0
            self.success = False
            return self.score

        intersection = set(retrieval_context) & set(context)
        self.score = len(intersection) / len(retrieval_context)

        self.success = self.score >= self.threshold
        return self.score

    def is_successful(self):
        return self.success

    @property
    def __name__(self):
        return "ContextualRelevancy(chunk-based)"
