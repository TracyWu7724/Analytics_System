"""Query normalization and lightweight rewriting before retrieval."""

from __future__ import annotations

import re
from typing import Callable

try:
    from ..rag_config import QueryPreparationConfig
except ImportError:
    from rag_config import QueryPreparationConfig


RewriteFn = Callable[[str], str]

# Minimum token length to attempt spell correction (short tokens are too ambiguous)
_MIN_CORRECT_LEN = 4
# Minimum rapidfuzz ratio to accept a correction (0–100)
_CORRECT_THRESHOLD = 82


def _build_vocab(known_terms: set[str]) -> set[str]:
    """
    Extract individual word tokens from known product IDs / source file names.
    e.g. {"loctite 243", "loctite_243_threadlocker.pdf"} →
         {"loctite", "243", "threadlocker"}
    """
    vocab: set[str] = set()
    for term in known_terms:
        for tok in re.split(r"[\s_\-./]+", term.lower()):
            tok = tok.strip()
            if tok and len(tok) >= _MIN_CORRECT_LEN:
                vocab.add(tok)
    return vocab


class QueryRewriter:
    """Normalize queries with optional domain-aware spell correction."""

    def __init__(
        self,
        config: QueryPreparationConfig | None = None,
        rewrite_fn: RewriteFn | None = None,
        known_terms: set[str] | None = None,
    ):
        self.config = config or QueryPreparationConfig()
        self.rewrite_fn = rewrite_fn
        self._vocab: set[str] = _build_vocab(known_terms) if known_terms else set()

    def normalize(self, query: str) -> str:
        text = query.strip()
        if self.config.lowercase:
            text = text.lower()
        if self.config.remove_punctuation:
            text = re.sub(r"[^\w\s]", " ", text)
        if self.config.collapse_whitespace:
            text = re.sub(r"\s+", " ", text)
        return text.strip()

    def correct_spelling(self, query: str) -> str:
        """
        Correct misspelled domain tokens using fuzzy matching against the
        product vocabulary (rapidfuzz).  Only corrects tokens that:
          - are at least _MIN_CORRECT_LEN characters long
          - are NOT already in the vocabulary (no change needed)
          - have a best fuzzy match above _CORRECT_THRESHOLD

        Conservative by design — pure English words are unlikely to appear
        in the product vocab, so they are left untouched.
        """
        if not self._vocab:
            return query

        try:
            from rapidfuzz import process, fuzz
        except ImportError:
            return query

        tokens = query.split()
        corrected = []
        for tok in tokens:
            # Skip short tokens, numeric tokens, already-known tokens
            if len(tok) < _MIN_CORRECT_LEN or tok.isdigit() or tok in self._vocab:
                corrected.append(tok)
                continue

            result = process.extractOne(tok, self._vocab, scorer=fuzz.ratio)
            if result is not None:
                match, score, _ = result
                if score >= _CORRECT_THRESHOLD and match != tok:
                    corrected.append(match)
                    continue

            corrected.append(tok)
        return " ".join(corrected)

    def rewrite(self, query: str) -> str:
        normalized = self.normalize(query)
        corrected  = self.correct_spelling(normalized)
        if self.rewrite_fn is None:
            return corrected
        rewritten = self.rewrite_fn(corrected)
        return self.normalize(rewritten)
