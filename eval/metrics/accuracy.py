"""Accuracy metric for RAG evaluation.

WrenAI's version executes both expected and actual *SQL* against the Wren
Engine, compares the resulting DataFrames, and assigns scores in three tiers:
    1. Exact / subset DataFrame match  → score = 1
    2. Partial column overlap           → score = fraction of columns matched
    3. Optional LLM semantic SQL check  → score = 1 or 0

Here there is no SQL or engine.  The equivalent tiers for free-text answers:
    1. Exact string match               → score = 1
    2. Token F1 (ROUGE-1 style)         → score = 2·P·R / (P+R)
       where P = overlap/actual tokens, R = overlap/expected tokens
    3. Optional LLM semantic check      → score = 1 or 0
       (uses the project's existing LLM registry; defaults to gemini-2.5-flash)

AccuracyMultiCandidateMetric aggregates per-question best scores across
multiple candidate answers.  It carries over unchanged from WrenAI because it
has no SQL dependency — it only reads from AccuracyMetric results.
"""

import asyncio
import traceback

import orjson
from deepeval.evaluate import TestResult
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase


def _token_set(text: str) -> set[str]:
    return {t.lower() for t in text.split() if t.strip()}


def _token_f1(actual: str, expected: str) -> float:
    actual_tokens = _token_set(actual)
    expected_tokens = _token_set(expected)

    if not actual_tokens or not expected_tokens:
        return 0.0

    intersection = actual_tokens & expected_tokens
    if not intersection:
        return 0.0

    precision = len(intersection) / len(actual_tokens)
    recall = len(intersection) / len(expected_tokens)
    return 2 * precision * recall / (precision + recall)


class AccuracyMetric(BaseMetric):
    def __init__(
        self,
        enable_semantics_comparison: bool = False,
        llm_model: str = "gemini-2.5-flash",
    ):
        self.threshold = 0
        self.score = 0
        self.enable_semantics_comparison = enable_semantics_comparison
        self._llm_model = llm_model

    def measure(self, test_case: LLMTestCase):
        return asyncio.run(self.a_measure(test_case))

    async def _check_answer_semantics(
        self, expected_answer: str, actual_answer: str
    ) -> float:
        """Ask an LLM whether the two answers are semantically equivalent."""
        try:
            # Import lazily so the metric is usable without the LLM registry
            # when enable_semantics_comparison=False.
            import sys
            import os

            # Allow running from repo root or from eval/ directly
            for path in [
                os.path.join(os.path.dirname(__file__), "..", "..", "backend"),
                os.path.join(os.path.dirname(__file__), "../../backend"),
            ]:
                abs_path = os.path.abspath(path)
                if abs_path not in sys.path:
                    sys.path.insert(0, abs_path)

            from services.text2sql.generation.llm_registry import get_llm

            system_prompt = (
                "You are an expert evaluator. Compare two answers and decide if they "
                "are semantically equivalent — conveying the same factual information.\n"
                "Return a JSON object with this schema:\n"
                '{ "reasoning": "<brief explanation>", "same": <true|false> }'
            )
            user_prompt = (
                f"Expected answer: {expected_answer}\n\n"
                f"Actual answer: {actual_answer}\n\n"
                "Are these semantically equivalent?"
            )

            llm = get_llm(self._llm_model)
            from langchain_core.messages import HumanMessage, SystemMessage

            response = llm.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
            content = response.content.strip()
            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            result = orjson.loads(content)
            return 1.0 if result.get("same") else 0.0
        except Exception as e:
            print(f"LLM semantic check failed: {e}")
            return 0.0

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs):
        try:
            actual = (test_case.actual_output or "").strip()
            expected = (test_case.expected_output or "").strip()

            # Tier 1: exact match
            if actual == expected:
                self.score = 1.0
                self.success = True
                return self.score

            # Tier 2: token F1
            self.score = _token_f1(actual, expected)

            # Tier 3: LLM semantic check when F1 is 0 and comparison is enabled
            if self.score == 0 and self.enable_semantics_comparison:
                print(f"before _check_answer_semantics: {self.score}")
                print(f"expected: {expected}")
                print(f"actual:   {actual}")
                self.score = await self._check_answer_semantics(expected, actual)
                print(f"after _check_answer_semantics: {self.score}")

        except Exception as e:
            self.error = f"Error occurred while evaluating the metric: {e}"
            traceback.print_exc()

        self.success = self.score >= self.threshold
        return self.score

    def is_successful(self):
        return self.success

    @property
    def __name__(self):
        return "Accuracy(token-F1)"


class AccuracyMultiCandidateMetric(BaseMetric):
    """Aggregate per-question best scores across multiple candidate answers.

    Carries over from WrenAI unchanged — no SQL dependency.
    Collect one AccuracyMetric result per candidate per question, then call
    measure() once at the end to get the mean best score across all questions.
    """

    def __init__(self):
        self.threshold = 0
        self.score = 0
        self._questions: dict[str, float] = {}

    def collect(self, test_case: LLMTestCase, result: TestResult):
        for metric in result.metrics_data:
            if metric.name != "Accuracy(token-F1)":
                continue
            # Keep the best score seen so far for this question
            self._questions[test_case.input] = max(
                self._questions.get(test_case.input, 0) or 0,
                metric.score or 0,
            )

    def measure(self):
        if not self._questions:
            return 0.0
        self.score = sum(self._questions.values()) / len(self._questions)
        self.success = self.score >= self.threshold
        return self.score

    def is_successful(self):
        return self.success

    @property
    def __name__(self):
        return "Accuracy(question-based)"
