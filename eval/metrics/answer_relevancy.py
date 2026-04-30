"""Answer relevancy metric for RAG evaluation.

Here there is no SQL — actual_output and expected_output are free-text answers.
We measure relevancy as the fraction of tokens in the actual answer that also
appear in the expected answer (precision-oriented token overlap), which asks:
"Is what the model said grounded in the reference answer?"
"""

import asyncio

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase


def _token_set(text: str) -> set[str]:
    return {t.lower() for t in text.split() if t.strip()}


class AnswerRelevancyMetric(BaseMetric):
    def __init__(self):
        self.threshold = 0
        self.score = 0

    def measure(self, test_case: LLMTestCase):
        return asyncio.run(self.a_measure(test_case))

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs):
        actual_tokens = _token_set(test_case.actual_output or "")
        expected_tokens = _token_set(test_case.expected_output or "")

        if not actual_tokens:
            self.score = 0.0
            self.success = False
            return self.score

        intersection = actual_tokens & expected_tokens
        self.score = len(intersection) / len(actual_tokens)

        self.success = self.score >= self.threshold
        return self.score

    def is_successful(self):
        return self.success

    @property
    def __name__(self):
        return "AnswerRelevancy(token-overlap)"
