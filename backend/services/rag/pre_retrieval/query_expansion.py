"""Generate retrieval-friendly query variants."""

from __future__ import annotations

import re

try:
    from ..rag_config import QueryPreparationConfig
    from ..rag_modeling import PreparedQuery
    from .query_rewrite import QueryRewriter
except ImportError:
    from rag_config import QueryPreparationConfig
    from rag_modeling import PreparedQuery
    from query_rewrite import QueryRewriter


class QueryExpander:
    """Create simple lexical variants without requiring an LLM."""

    SYNONYMS = {
        "spec": ["specification", "technical specification"],
        "specs": ["specification", "technical specifications"],
        "sds": ["safety data sheet", "safety sheet"],
        "tds": ["technical data sheet", "datasheet"],
        "adhesive": ["glue", "bonding material"],
        "temperature": ["heat", "operating temperature"],
        "viscosity": ["thickness", "flow resistance"],
    }

    def __init__(self, config: QueryPreparationConfig | None = None, rewriter: QueryRewriter | None = None):
        self.config = config or QueryPreparationConfig()
        self.rewriter = rewriter or QueryRewriter(self.config)

    def expand(self, query: str) -> PreparedQuery:
        rewritten = self.rewriter.rewrite(query)
        expansions: list[str] = []

        tokens = rewritten.split()
        for token in tokens:
            for synonym in self.SYNONYMS.get(token, []):
                expansions.append(rewritten.replace(token, synonym))

        quoted_phrases = re.findall(r'"([^"]+)"', query)
        expansions.extend(quoted_phrases)

        if "how" in tokens and "use" in tokens:
            expansions.append(rewritten.replace("how", "instructions to").replace("use", "apply"))
        if "what" in tokens and "is" in tokens:
            expansions.append(rewritten.replace("what is", "definition of"))

        deduped = self._dedupe(expansions)
        if not self.config.keep_original and rewritten in deduped:
            deduped.remove(rewritten)

        return PreparedQuery(
            original=query.strip(),
            rewritten=rewritten,
            expansions=deduped[: self.config.max_expansions],
        )

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            cleaned = re.sub(r"\s+", " ", item).strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result
