"""Contextual recall metric for RAG evaluation.

WrenAI's version derives expected context by running the *expected SQL* through
the Wren Engine analysis API to get table.column pairs, then measures what
fraction of those were present in retrieval_context.

Here there is no SQL. context (the ideal/reference chunks, provided in the test
case) plays the role of expected_units. We measure what fraction of the ideal
chunks the retriever actually returned.

Formula:
    score = |retrieval_context ∩ context| / |context|
"""

import asyncio

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase


class ContextualRecallMetric(BaseMetric):
    def __init__(self):
        self.threshold = 0
        self.score = 0

    def measure(self, test_case: LLMTestCase):
        return asyncio.run(self.a_measure(test_case))

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs):
        context = test_case.context or []
        retrieval_context = test_case.retrieval_context or []

        if not context:
            self.score = 0.0
            self.success = False
            return self.score

        intersection = set(retrieval_context) & set(context)
        self.score = len(intersection) / len(context)

        self.success = self.score >= self.threshold
        return self.score

    def is_successful(self):
        return self.success

    @property
    def __name__(self):
        return "ContextualRecall(chunk-based)"
