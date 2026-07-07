"""
nlp_utils.py — Shared NLP utilities.

Provides a lazy-loaded spaCy model singleton so it's loaded at most once
per process, even when used by multiple modules (entity extraction, KG builder, etc).
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_spacy_nlp = None
_spacy_model_name = "en_core_web_sm"


def load_spacy(model_name: str = _spacy_model_name):
    """Return the shared spaCy NLP model, loading it on first call."""
    global _spacy_nlp, _spacy_model_name
    if _spacy_nlp is None or model_name != _spacy_model_name:
        try:
            import spacy
            _spacy_nlp = spacy.load(model_name)
            _spacy_model_name = model_name
            logger.info(f"[NLP] Loaded spaCy model: {model_name}")
        except Exception as exc:
            logger.warning(f"[NLP] Failed to load spaCy model '{model_name}': {exc}")
            _spacy_nlp = None
    return _spacy_nlp
