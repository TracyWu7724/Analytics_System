import os
from typing import Any, Dict

from langchain_google_genai import ChatGoogleGenerativeAI


LLM_MODELS: Dict[str, Dict[str, str]] = {
    "gemini-2.5-flash": {"provider": "google", "display_name": "Gemini 2.5 Flash", "requires": "GEMINI_API_KEY"},
    "gpt-4o": {"provider": "openai", "display_name": "GPT-4o", "requires": "OPENAI_API_KEY"},
    "gpt-4o-mini": {"provider": "openai", "display_name": "GPT-4o Mini", "requires": "OPENAI_API_KEY"},
    "claude-sonnet-4-5": {"provider": "anthropic", "display_name": "Claude Sonnet 4.5", "requires": "ANTHROPIC_API_KEY"},
    "claude-haiku-4-5": {"provider": "anthropic", "display_name": "Claude Haiku 4.5", "requires": "ANTHROPIC_API_KEY"},
}

DEFAULT_LLM_MODEL = "gemini-2.5-flash"
_llm_cache: Dict[str, Any] = {}


def get_llm(model_name: str = DEFAULT_LLM_MODEL):
    if model_name in _llm_cache:
        return _llm_cache[model_name]

    if model_name not in LLM_MODELS:
        raise ValueError(f"Unknown model '{model_name}'. Available: {list(LLM_MODELS)}")

    info = LLM_MODELS[model_name]
    provider = info["provider"]
    api_key = os.getenv(info["requires"])
    if not api_key:
        raise ValueError(f"Model '{model_name}' requires {info['requires']} to be set.")

    if provider == "google":
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=0.0,
            max_output_tokens=4000,
        )
    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=model_name,
            openai_api_key=api_key,
            temperature=0.0,
            max_tokens=4000,
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(
            model=model_name,
            anthropic_api_key=api_key,
            temperature=0.0,
            max_tokens=4000,
        )
    else:
        raise ValueError(f"Unknown provider '{provider}'")

    _llm_cache[model_name] = llm
    return llm


def list_llm_models() -> dict:
    return {
        "models": [
            {
                "id": model_id,
                "display_name": info["display_name"],
                "provider": info["provider"],
                "available": bool(os.getenv(info["requires"])),
            }
            for model_id, info in LLM_MODELS.items()
        ],
        "default": DEFAULT_LLM_MODEL,
    }
