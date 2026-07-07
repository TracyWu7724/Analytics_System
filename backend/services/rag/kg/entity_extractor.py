"""
entity_extractor.py — Extract named entities from document chunks.

Uses spaCy NER plus product-code patterns (e.g. "LOCTITE 243", "3M VHB").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

try:
    from ...utils.nlp_utils import load_spacy
except ImportError:
    from services.utils.nlp_utils import load_spacy

_PRODUCT_CODE = re.compile(
    r"\b([A-Z]{2,}(?:\s+\d[\w-]*)+|[A-Z]{2,}-\d[\w-]*)\b"
)

ENTITY_TYPES = {"PRODUCT", "ORG", "PERSON", "GPE", "LOC", "NORP", "EVENT", "WORK_OF_ART"}


@dataclass
class Entity:
    text: str
    label: str
    source: str = ""  # source_file or chunk id
    mentions: int = 1


def extract_entities(text: str, source: str = "") -> list[Entity]:
    """
    Extract named entities from text.
    Returns deduped list of Entity objects.
    """
    found: dict[str, Entity] = {}

    # spaCy NER
    nlp = load_spacy()
    if nlp is not None:
        try:
            doc = nlp(text[:50_000])  # cap to avoid memory issues
            for ent in doc.ents:
                if ent.label_ in ENTITY_TYPES:
                    key = ent.text.strip().lower()
                    if key in found:
                        found[key].mentions += 1
                    else:
                        found[key] = Entity(text=ent.text.strip(), label=ent.label_, source=source)
        except Exception:
            pass

    # Product code patterns (e.g. "LOCTITE 243", "VHB 4950")
    for m in _PRODUCT_CODE.finditer(text):
        key = m.group(0).strip().lower()
        if key not in found:
            found[key] = Entity(text=m.group(0).strip(), label="PRODUCT", source=source)

    return list(found.values())
