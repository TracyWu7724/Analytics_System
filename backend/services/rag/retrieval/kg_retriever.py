"""
kg_retriever.py — Expand a query using the knowledge graph.

Before FAISS retrieval, expand named entities in the query to related
concepts from the KG.  This improves recall for implicit product questions
(e.g. "what replaces LOCTITE 243?" → also retrieves LOCTITE 2400 chunks).
"""

from __future__ import annotations

import re
from typing import Optional

try:
    from ...utils.nlp_utils import load_spacy
    from ..kg.knowledge_graph import KnowledgeGraph
except ImportError:
    from services.utils.nlp_utils import load_spacy
    from rag.kg.knowledge_graph import KnowledgeGraph


_PRODUCT_CODE = re.compile(r"\b([A-Z]{2,}(?:\s+\d[\w-]*)+|[A-Z]{2,}-\d[\w-]*)\b")


class KGRetriever:
    """Expand queries using the knowledge graph."""

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg

    def expand_query(self, query: str, max_expansions: int = 5) -> list[str]:
        """
        Return additional query strings derived from KG neighbors of entities
        mentioned in `query`.
        """
        entities = self._extract_entities(query)
        if not entities:
            return []

        expansions: list[str] = []
        seen: set[str] = set(e.lower() for e in entities)

        for ent in entities:
            neighbors = self.kg.expand_entity(ent, hops=1)
            for nbr in neighbors:
                if nbr.lower() not in seen:
                    seen.add(nbr.lower())
                    expansions.append(nbr)
                    if len(expansions) >= max_expansions:
                        return expansions

        return expansions

    def build_expanded_query(self, query: str) -> str:
        """
        Return the query enriched with related entity names from the KG.
        If no expansions found, return the original query unchanged.
        """
        expansions = self.expand_query(query)
        if not expansions:
            return query
        return query + " " + " ".join(expansions)

    def _extract_entities(self, text: str) -> list[str]:
        entities: list[str] = []

        # Product code pattern
        for m in _PRODUCT_CODE.finditer(text):
            entities.append(m.group(0).strip())

        # spaCy NER
        nlp = load_spacy()
        if nlp is not None:
            try:
                doc = nlp(text[:10_000])
                for ent in doc.ents:
                    if ent.label_ in {"ORG", "PRODUCT", "PERSON", "GPE"}:
                        entities.append(ent.text.strip())
            except Exception:
                pass

        # Deduplicate preserving order
        seen: set[str] = set()
        result: list[str] = []
        for e in entities:
            k = e.lower()
            if k not in seen:
                seen.add(k)
                result.append(e)
        return result
