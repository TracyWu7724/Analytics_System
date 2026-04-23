"""Query normalization and lightweight rewriting before retrieval."""

from __future__ import annotations

import re
from typing import Callable

try:
    from ..rag_config import QueryPreparationConfig
except ImportError:
    from rag_config import QueryPreparationConfig


RewriteFn = Callable[[str], str]


class QueryRewriter:
    """Normalize queries with optional custom rewrite logic."""

    def __init__(self, config: QueryPreparationConfig | None = None, rewrite_fn: RewriteFn | None = None):
        self.config = config or QueryPreparationConfig()
        self.rewrite_fn = rewrite_fn

    def normalize(self, query: str) -> str:
        text = query.strip()
        if self.config.lowercase:
            text = text.lower()
        if self.config.remove_punctuation:
            text = re.sub(r"[^\w\s]", " ", text)
        if self.config.collapse_whitespace:
            text = re.sub(r"\s+", " ", text)
        return text.strip()

    def rewrite(self, query: str) -> str:
        normalized = self.normalize(query)
        if self.rewrite_fn is None:
            return normalized
        rewritten = self.rewrite_fn(normalized)
        return self.normalize(rewritten)
