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

from ._faithfulness_core import faithfulness_score


class FaithfulnessMetric(BaseMetric):
    def __init__(self):
        self.threshold = 0
        self.score = 0

    def measure(self, test_case: LLMTestCase):
        return asyncio.run(self.a_measure(test_case))

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs):
        self.score = faithfulness_score(
            test_case.actual_output or "", test_case.retrieval_context or []
        )
        self.success = self.score >= self.threshold
        return self.score

    def is_successful(self):
        return self.success

    @property
    def __name__(self):
        return "Faithfulness(token-grounding)"
