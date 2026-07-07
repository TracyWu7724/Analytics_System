"""
relation_extractor.py — Extract relations between entities from text chunks.

Uses simple pattern-based extraction for known relation types (is_used_for,
is_compatible_with, replaces, etc.) and optionally an LLM for open-domain relations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .entity_extractor import Entity

_USED_FOR = re.compile(
    r"(?P<subj>[A-Z][\w\s-]{2,30}?)\s+"
    r"(?:is used for|can be used for|is suitable for|is applied to|is designed for)\s+"
    r"(?P<obj>[a-z][\w\s,]{3,60}?)(?:[.;,]|$)",
    re.IGNORECASE,
)
_COMPATIBLE = re.compile(
    r"(?P<subj>[A-Z][\w\s-]{2,30}?)\s+"
    r"(?:is compatible with|works with|bonds to|adheres to)\s+"
    r"(?P<obj>[a-z][\w\s,]{3,60}?)(?:[.;,]|$)",
    re.IGNORECASE,
)
_REPLACES = re.compile(
    r"(?P<subj>[A-Z][\w\s-]{2,30}?)\s+"
    r"(?:replaces|supersedes|is the successor of)\s+"
    r"(?P<obj>[A-Z][\w\s-]{2,30}?)(?:[.;,]|$)",
    re.IGNORECASE,
)

PATTERNS = [
    ("is_used_for",      _USED_FOR),
    ("is_compatible_with", _COMPATIBLE),
    ("replaces",         _REPLACES),
]


@dataclass
class Relation:
    subject: str
    predicate: str
    object: str
    source: str = ""
    confidence: float = 1.0


def extract_relations(
    text: str,
    entities: list[Entity],
    source: str = "",
) -> list[Relation]:
    """
    Extract (subject, predicate, object) triples from text.
    Only returns relations where the subject appears in `entities`.
    """
    entity_texts = {e.text.lower() for e in entities}
    relations: list[Relation] = []

    for predicate, pattern in PATTERNS:
        for m in pattern.finditer(text):
            subj = m.group("subj").strip()
            obj  = m.group("obj").strip()
            if subj.lower() in entity_texts or any(
                subj.lower().startswith(e) or e.startswith(subj.lower())
                for e in entity_texts
            ):
                relations.append(Relation(
                    subject=subj, predicate=predicate, object=obj,
                    source=source, confidence=0.85,
                ))

    return relations
