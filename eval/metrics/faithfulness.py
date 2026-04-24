"""Faithfulness metric for RAG evaluation.

WrenAI's version extracts table.column pairs from the actual *SQL* via the
Wren Engine API, then measures:
    |actual_columns ∩ retrieval_context_columns| / |actual_columns|

This asks: "Did the model only reference columns that were in the retrieved
schema context?" — i.e. is the SQL grounded in what was retrieved?

Here there is no SQL. The equivalent question is:
"Is the generated answer grounded in the retrieved document chunks?"

We approximate this as the fraction of content words in actual_output that
appear in the combined text of retrieval_context. Stop-words are excluded so
boilerplate terms ("the", "is") don't inflate the score.
"""

import asyncio

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "on",
    "at", "by", "for", "with", "from", "and", "or", "but", "not", "it",
    "its", "this", "that", "these", "those", "i", "you", "he", "she",
    "we", "they", "what", "which", "who", "whom", "how", "when", "where",
}


def _content_tokens(text: str) -> set[str]:
    return {
        t.lower().strip(".,;:!?\"'()")
        for t in text.split()
        if t.lower().strip(".,;:!?\"'()") and t.lower() not in _STOP_WORDS
    }


class FaithfulnessMetric(BaseMetric):
    def __init__(self):
        self.threshold = 0
        self.score = 0

    def measure(self, test_case: LLMTestCase):
        return asyncio.run(self.a_measure(test_case))

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs):
        actual_tokens = _content_tokens(test_case.actual_output or "")

        if not actual_tokens:
            self.score = 0.0
            self.success = False
            return self.score

        # Combine all retrieved chunks into a single token pool
        retrieved_text = " ".join(test_case.retrieval_context or [])
        retrieved_tokens = _content_tokens(retrieved_text)

        intersection = actual_tokens & retrieved_tokens
        self.score = len(intersection) / len(actual_tokens)

        self.success = self.score >= self.threshold
        return self.score

    def is_successful(self):
        return self.success

    @property
    def __name__(self):
        return "Faithfulness(token-grounding)"
