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

# ── Comparative pattern detection ─────────────────────────────────────────────
# Maps (direction, category_hint) → concept queries to add for retrieval.
# These retrieve chunks from *alternative* products rather than the named one.
_COMPARATIVE_PATTERNS: list[tuple[re.Pattern, list[str]]] = [
    # "weaker than", "less strong than", "lower strength than"
    (re.compile(r"\b(weaker|less strong|lower strength)\b", re.I),
     ["lower strength adhesive recommendation",
      "medium strength adhesive",
      "low strength adhesive product"]),
    # "stronger than", "more strong than", "higher strength than"
    (re.compile(r"\b(stronger|more strong|higher strength)\b", re.I),
     ["higher strength adhesive recommendation",
      "high strength adhesive product"]),
    # "alternative to", "instead of", "similar to", "replace"
    (re.compile(r"\b(alternative to|instead of|similar to|replace|substitute)\b", re.I),
     ["adhesive alternative recommendation",
      "similar product recommendation"]),
]


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
        # threadlocker family
        "threadlocker": ["thread locking adhesive", "threadlocking"],
        "threadlockers": ["thread locking adhesives", "threadlocking products"],
        "threadlocking": ["thread locking", "threadlocker"],
        # strength levels — query normaliser strips hyphens, so "medium-strength" → "medium strength"
        "medium": ["medium strength", "medium-strength"],
        "high": ["high strength", "high-strength"],
        "low": ["low strength", "low-strength"],
        # application types
        "sealant": ["thread sealant", "pipe sealant", "sealing"],
        "retaining": ["retaining compound", "cylindrical retention"],
        "structural": ["structural adhesive", "structural bonding"],
    }

    def __init__(
        self,
        config: QueryPreparationConfig | None = None,
        rewriter: QueryRewriter | None = None,
        known_terms: set[str] | None = None,
    ):
        self.config = config or QueryPreparationConfig()
        self.rewriter = rewriter or QueryRewriter(self.config, known_terms=known_terms)

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

        # Comparative queries — add concept-level searches so the retriever
        # fetches chunks from *alternative* products, not just the named one.
        rerank_query = ""
        for pattern, concept_queries in _COMPARATIVE_PATTERNS:
            if pattern.search(query):
                expansions.extend(concept_queries)
                # Use the first concept query for reranking so alternative
                # products score higher than the named reference product.
                rerank_query = concept_queries[0]
                break  # one match is enough

        deduped = self._dedupe(expansions)
        if not self.config.keep_original and rewritten in deduped:
            deduped.remove(rewritten)

        return PreparedQuery(
            original=query.strip(),
            rewritten=rewritten,
            expansions=deduped[: self.config.max_expansions],
            rerank_query=rerank_query,
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
