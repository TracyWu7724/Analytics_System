"""Unit tests for services.rag.generation.generation_o (build_prompt, ask_llm)."""

from unittest.mock import MagicMock, patch

import pytest

from services.rag.generation.generation_o import ask_llm, build_prompt


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_contains_system_block(self):
        prompt = build_prompt(context="ctx", question="q")
        assert "[SYSTEM]" in prompt

    def test_contains_context_block(self):
        prompt = build_prompt(context="tensile strength 25 MPa", question="What is the strength?")
        assert "[CONTEXT]" in prompt
        assert "tensile strength 25 MPa" in prompt

    def test_contains_question_block(self):
        prompt = build_prompt(context="ctx", question="What is the cure time?")
        assert "[QUESTION]" in prompt
        assert "What is the cure time?" in prompt

    def test_contains_answer_marker(self):
        prompt = build_prompt(context="ctx", question="q")
        assert "[ANSWER]" in prompt

    def test_no_history_block_when_omitted(self):
        prompt = build_prompt(context="ctx", question="q")
        assert "[CONVERSATION HISTORY]" not in prompt

    def test_history_block_present_when_provided(self):
        history = [
            {"role": "user", "content": "What is this?"},
            {"role": "assistant", "content": "It is an adhesive."},
        ]
        prompt = build_prompt(context="ctx", question="Tell me more.", history=history)
        assert "[CONVERSATION HISTORY]" in prompt
        assert "What is this?" in prompt
        assert "It is an adhesive." in prompt

    def test_empty_history_list_omits_block(self):
        prompt = build_prompt(context="ctx", question="q", history=[])
        assert "[CONVERSATION HISTORY]" not in prompt

    def test_prompt_ordering(self):
        prompt = build_prompt(context="ctx", question="q")
        system_pos = prompt.index("[SYSTEM]")
        context_pos = prompt.index("[CONTEXT]")
        question_pos = prompt.index("[QUESTION]")
        answer_pos = prompt.index("[ANSWER]")
        assert system_pos < context_pos < question_pos < answer_pos


# ---------------------------------------------------------------------------
# ask_llm — Gemini dispatch (mocked)
# ---------------------------------------------------------------------------

class TestAskLlmGemini:
    def test_calls_gemini_helper(self):
        with patch("services.rag.generation.generation_o._ask_gemini", return_value="answer") as mock:
            result = ask_llm("prompt", llm_origin="Gemini", llm_model="gemini-2.5-flash")
        mock.assert_called_once_with("prompt", "gemini-2.5-flash", 0.2, 2048)
        assert result == "answer"

    def test_custom_temperature_and_max_tokens(self):
        with patch("services.rag.generation.generation_o._ask_gemini", return_value="ok") as mock:
            ask_llm("prompt", llm_origin="Gemini", temperature=0.7, max_tokens=512)
        _, args = mock.call_args[0], mock.call_args[0]
        assert mock.call_args[0][2] == 0.7
        assert mock.call_args[0][3] == 512


# ---------------------------------------------------------------------------
# ask_llm — OpenAI dispatch (mocked)
# ---------------------------------------------------------------------------

class TestAskLlmOpenAI:
    def test_calls_openai_helper(self):
        with patch("services.rag.generation.generation_o._ask_openai", return_value="answer") as mock:
            result = ask_llm("prompt", llm_origin="OpenAI", llm_model="gpt-4o")
        mock.assert_called_once_with("prompt", "gpt-4o", 0.2, 2048, None)
        assert result == "answer"

    def test_passes_base_url(self):
        with patch("services.rag.generation.generation_o._ask_openai", return_value="ok") as mock:
            ask_llm("prompt", llm_origin="OpenAI", base_url="http://localhost:8080/v1")
        assert mock.call_args[0][4] == "http://localhost:8080/v1"


# ---------------------------------------------------------------------------
# ask_llm — Qwen / vLLM dispatch (mocked)
# ---------------------------------------------------------------------------

class TestAskLlmQwen:
    def test_local_hf_when_use_vllm_false(self):
        with patch("services.rag.generation.generation_o._ask_local_hf", return_value="ok") as mock:
            ask_llm("prompt", llm_origin="Qwen", llm_model="Qwen/Qwen2-7B", use_vllm=False)
        mock.assert_called_once()

    def test_vllm_when_use_vllm_true(self):
        with patch("services.rag.generation.generation_o._ask_vllm", return_value="ok") as mock:
            ask_llm("prompt", llm_origin="Qwen", use_vllm=True)
        mock.assert_called_once()


# ---------------------------------------------------------------------------
# ask_llm — error handling
# ---------------------------------------------------------------------------

class TestAskLlmErrors:
    def test_raises_value_error_for_unknown_origin(self):
        with pytest.raises(ValueError, match="Unknown llm_origin"):
            ask_llm("prompt", llm_origin="UnknownProvider")

    def test_wraps_sdk_errors_as_runtime_error(self):
        with patch(
            "services.rag.generation.generation_o._ask_gemini",
            side_effect=Exception("network failure"),
        ):
            with pytest.raises(RuntimeError, match="LLM call failed"):
                ask_llm("prompt", llm_origin="Gemini")

    def test_value_error_from_missing_api_key_propagates(self):
        with patch(
            "services.rag.generation.generation_o._ask_gemini",
            side_effect=ValueError("GEMINI_API_KEY environment variable is not set."),
        ):
            with pytest.raises(ValueError):
                ask_llm("prompt", llm_origin="Gemini")
