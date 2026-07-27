"""
generation_o.py — LLM generation helpers for the RAG pipeline.

Supports:
  - Google Gemini  (google-genai SDK)
  - OpenAI-compatible APIs  (openai SDK, works with OpenAI and vLLM servers)
  - Local HuggingFace models  (transformers pipeline, CPU/GPU)
"""

from __future__ import annotations

import os
from typing import Optional

try:
    from observability.metrics.costs import record_llm_usage
except Exception:
    record_llm_usage = None


def build_prompt(
    context: str,
    question: str,
    history: Optional[list[dict]] = None,
) -> str:
    """
    Assemble a RAG prompt from retrieved context, the user question,
    and an optional conversation history.

    Args:
        context:  Retrieved passage(s), already joined into a single string.
        question: The user's current question.
        history:  List of {"role": "user"|"assistant", "content": str} dicts,
                  most-recent last.  Pass None or [] for single-turn use.

    Returns:
        A single string suitable for passing to ask_llm().
    """
    system = (
        "You are a helpful product specialist for Loctite adhesives. "
        "Answer the user's question using the information in the provided context. "
        "If the question asks for product recommendations or alternatives, describe "
        "the properties of the products present in the context — even if the context "
        "does not explicitly compare them. Use the available product data to help the "
        "user choose. "
        "If the answer truly cannot be found in the context, say so briefly. "
        "Be concise and factual."
    )

    parts: list[str] = [
        f"[SYSTEM]\n{system}",
        f"\n[CONTEXT]\n{context}",
    ]

    if history:
        history_text = "\n".join(
            f"{turn['role'].capitalize()}: {turn['content']}"
            for turn in history
        )
        parts.append(f"\n[CONVERSATION HISTORY]\n{history_text}")

    parts.append(f"\n[QUESTION]\n{question}")
    parts.append("\n[ANSWER]")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Private per-provider helpers
# ---------------------------------------------------------------------------

def _ask_gemini(
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    from google import genai  # pip install google-genai
    from google.genai import types as genai_types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    if record_llm_usage is not None:
        record_llm_usage(model, response, pipeline="rag")
    return response.text.strip()


def _ask_openai(
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    base_url: Optional[str],
) -> str:
    from openai import OpenAI  # pip install openai

    api_key = os.environ.get("OPENAI_API_KEY", "EMPTY")
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if record_llm_usage is not None:
        record_llm_usage(model, response, pipeline="rag")
    return response.choices[0].message.content.strip()


def _ask_vllm(
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    base_url: str,
) -> str:
    """
    Query a vLLM server that exposes an OpenAI-compatible /v1 endpoint.
    Defaults to http://localhost:8080/v1 if base_url is not given.
    """
    effective_url = base_url or "http://localhost:8080/v1"
    return _ask_openai(
        prompt=prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        base_url=effective_url,
    )


def _ask_ollama(
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    base_url: str = "http://localhost:11434/v1",
) -> str:
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key="ollama")
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if record_llm_usage is not None:
        record_llm_usage(model, response, pipeline="rag")
    return response.choices[0].message.content.strip()


def _ask_local_hf(
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """
    Run inference with a local HuggingFace model via the transformers pipeline.
    Downloads the model on first call; subsequent calls reuse the cached weights.
    """
    from transformers import pipeline  # pip install transformers accelerate

    generator = pipeline(
        "text-generation",
        model=model,
        device_map="auto",
    )
    outputs = generator(
        prompt,
        max_new_tokens=max_tokens,
        temperature=temperature,
        do_sample=temperature > 0,
        return_full_text=False,
    )
    return outputs[0]["generated_text"].strip()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def ask_llm(
    prompt: str,
    llm_origin: str = "Gemini",
    llm_model: str = "gemini-2.5-flash",
    *,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    base_url: Optional[str] = None,
    use_vllm: bool = False,
) -> str:
    """
    Send *prompt* to the chosen LLM and return the text response.

    Args:
        prompt:      The fully-assembled prompt string (use build_prompt()).
        llm_origin:  Provider name — "Gemini", "OpenAI", or "Qwen".
        llm_model:   Model identifier (provider-specific).
        temperature: Sampling temperature (keyword-only).
        max_tokens:  Maximum tokens to generate (keyword-only).
        base_url:    Custom API base URL, e.g. for a vLLM server (keyword-only).
        use_vllm:    When llm_origin="Qwen", query a vLLM server instead of
                     loading the model locally (keyword-only).

    Returns:
        The model's text response as a plain string.

    Raises:
        ValueError:  For missing credentials or unknown provider.
        Exception:   Propagates SDK-level errors after wrapping with context.
    """
    try:
        if llm_origin == "Gemini":
            return _ask_gemini(prompt, llm_model, temperature, max_tokens)

        elif llm_origin == "OpenAI":
            return _ask_openai(prompt, llm_model, temperature, max_tokens, base_url)

        elif llm_origin == "Ollama":
            ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434") + "/v1"
            return _ask_ollama(prompt, llm_model, temperature, max_tokens, ollama_url)

        elif llm_origin == "Qwen":
            if use_vllm:
                return _ask_vllm(prompt, llm_model, temperature, max_tokens, base_url or "")
            else:
                return _ask_local_hf(prompt, llm_model, temperature, max_tokens)

        else:
            raise ValueError(
                f"Unknown llm_origin '{llm_origin}'. "
                "Choose from: 'Gemini', 'OpenAI', 'Ollama', 'Qwen'."
            )

    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"LLM call failed (origin={llm_origin}, model={llm_model}): {exc}"
        ) from exc
