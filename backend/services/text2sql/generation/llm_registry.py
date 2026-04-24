import os
from typing import Any, Dict

from langchain_google_genai import ChatGoogleGenerativeAI

_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

LLM_MODELS: Dict[str, Dict[str, str]] = {
    "gemini-2.5-flash": {"provider": "google",  "display_name": "Gemini 2.5 Flash", "requires": "GEMINI_API_KEY"},
    "gpt-4o":           {"provider": "openai",  "display_name": "GPT-4o",           "requires": "OPENAI_API_KEY"},
    "gpt-4o-mini":      {"provider": "openai",  "display_name": "GPT-4o Mini",      "requires": "OPENAI_API_KEY"},
    "gpt-5.4":          {"provider": "openai",  "display_name": "GPT-5.4",          "requires": "OPENAI_API_KEY"},
    "gemma4":           {"provider": "ollama",  "display_name": "Gemma 4",          "requires": "", "ollama_model": "gemma4"},
    "qwen3-0.6b":       {"provider": "ollama",  "display_name": "Qwen3 0.6B",       "requires": "", "ollama_model": "qwen3:0.6b"},
    "qwen3-27b":        {"provider": "ollama",  "display_name": "Qwen3 27B",        "requires": "", "ollama_model": "qwen3.6:27b"},
}

DEFAULT_LLM_MODEL = "gemini-2.5-flash"
_llm_cache: Dict[str, Any] = {}


def _is_ollama_available() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(_OLLAMA_BASE_URL, timeout=1)
        return True
    except Exception:
        return False


def get_llm(model_name: str = DEFAULT_LLM_MODEL):
    if model_name in _llm_cache:
        return _llm_cache[model_name]

    if model_name not in LLM_MODELS:
        raise ValueError(f"Unknown model '{model_name}'. Available: {list(LLM_MODELS)}")

    info = LLM_MODELS[model_name]
    provider = info["provider"]

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        llm = ChatOllama(
            model=info.get("ollama_model", model_name),
            base_url=_OLLAMA_BASE_URL,
            temperature=0.0,
        )
    else:
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
        else:
            raise ValueError(f"Unknown provider '{provider}'")

    _llm_cache[model_name] = llm
    return llm


def list_llm_models() -> dict:
    ollama_up = _is_ollama_available()
    return {
        "models": [
            {
                "id": model_id,
                "display_name": info["display_name"],
                "provider": info["provider"],
                "available": ollama_up if info["provider"] == "ollama" else bool(os.getenv(info["requires"])),
            }
            for model_id, info in LLM_MODELS.items()
        ],
        "default": DEFAULT_LLM_MODEL,
    }
