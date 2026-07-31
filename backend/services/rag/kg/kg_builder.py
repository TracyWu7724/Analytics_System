"""
kg_builder.py — Build a KnowledgeGraph from indexed document chunks.

Called after a PDF is indexed. Iterates all chunk texts, extracts entities
and relations, and updates the persistent KG.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from itertools import combinations
from pathlib import Path
from typing import Optional

from .entity_extractor import extract_entities
from .knowledge_graph import KnowledgeGraph
from .relation_extractor import extract_relations

logger = logging.getLogger(__name__)

# Cap on entities per chunk considered for co-occurrence pairing, to keep the
# edge count from a single dense chunk from blowing up combinatorially.
_MAX_COOCCUR_ENTITIES = 10


class KGBuilder:
    """Build and persist a KnowledgeGraph from RAG metadata chunks."""

    def __init__(self, kg: KnowledgeGraph, kg_path: str):
        self.kg = kg
        self.kg_path = kg_path

    def build_from_chunks(self, chunks: list[dict]) -> None:
        """
        Process a list of chunk dicts [{text, source_file, ...}] and update the KG.
        Each chunk updates the graph incrementally then saves.
        """
        total = len(chunks)
        for i, chunk in enumerate(chunks):
            text   = chunk.get("text", "")
            source = chunk.get("source_file", chunk.get("id", ""))
            if not text.strip():
                continue
            try:
                entities = extract_entities(text, source=source)
                for e in entities:
                    self.kg.add_entity(e.text, label=e.label, source=source)

                relations = extract_relations(text, entities, source=source)
                for r in relations:
                    self.kg.add_relation(r.subject, r.predicate, r.object, source=source, confidence=r.confidence)

                # Fallback: co-occurrence edges. The pattern-based extractor above only
                # fires on exact phrasing ("is compatible with", "bonds to", ...), which
                # real documents rarely use verbatim — without this, entities accumulate
                # as isolated nodes and the graph ends up with ~0 edges. Co-occurrence
                # within a chunk is a weaker but far more common signal, and it's what
                # lets entities shared across files bridge into a single connected graph.
                typed_pairs = {frozenset((r.subject.lower(), r.object.lower())) for r in relations}
                unique_entities = list({e.text.lower(): e for e in entities}.values())
                for e1, e2 in combinations(unique_entities[:_MAX_COOCCUR_ENTITIES], 2):
                    pair = frozenset((e1.text.lower(), e2.text.lower()))
                    if pair in typed_pairs:
                        continue
                    self.kg.add_relation(e1.text, "co_occurs_with", e2.text, source=source, confidence=0.4)
                    self.kg.add_relation(e2.text, "co_occurs_with", e1.text, source=source, confidence=0.4)
            except Exception as exc:
                logger.debug(f"[KGBuilder] chunk {i} failed: {exc}")

        self.kg.save(self.kg_path)
        logger.info(f"[KGBuilder] Built from {total} chunks → {self.kg.stats()}")

    def build_async(self, chunks: list[dict]) -> None:
        """Kick off build_from_chunks in a daemon thread."""
        t = threading.Thread(target=self.build_from_chunks, args=(chunks,), daemon=True)
        t.start()
