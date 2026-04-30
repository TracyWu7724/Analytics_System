"""
query_value_extractor.py — Multi-strategy extraction of potential filter values
from a natural-language user question.

Strategy 1 — Rule-based regexes:
    • Quoted strings    "Tracy Wu",  'Alice'
    • Title-Case runs   Tracy Wu,    New York
    • ISO / slash dates 2024-01-01,  01/2024

Strategy 2 — spaCy NER + noun chunks (lazy load; graceful no-op if unavailable):
    Entity types indexed: PERSON  ORG  GPE  PRODUCT  EVENT  WORK_OF_ART  FAC  LOC

Candidates are deduplicated and ranked:
    quoted  >  spaCy NER  >  rule titlecase  >  spaCy noun chunk  >  date
"""

from __future__ import annotations

import re
from typing import List, Dict

# ── Rule-based patterns ────────────────────────────────────────────────────────

_QUOTED     = re.compile(r'"([^"]{1,80})"|\'([^\']{1,80})\'')
_TITLECASE  = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')   # "Tracy Wu"
_SINGLE_CAP = re.compile(r'\b([A-Z][a-z]{2,})\b')                    # "Alice"
# Brand + product number: "Loctite 401", "3M 9472LE", "Loctite 243 Threadlocker"
_BRAND_NUM  = re.compile(r'\b([A-Z][a-zA-Z]{1,}(?:\s+\d[\w\-]*)+(?:\s+[A-Z][a-z]+)*)\b')

# Words unlikely to be filter values even when capitalised
_QUESTION_STOPWORDS = {
    "show", "tell", "give", "list", "find", "fetch", "return", "display",
    "what", "where", "who", "which", "how", "when", "why",
    "the", "a", "an", "and", "or", "not", "for", "in", "on", "at", "to",
    "by", "is", "are", "was", "were", "has", "have", "had", "been",
    "do", "does", "did", "will", "would", "could", "should", "may",
    "all", "some", "any", "each", "every", "both", "many", "much",
    "this", "that", "these", "those", "there", "here",
    "project", "projects", "record", "records", "sales", "data", "table",
    "database", "column", "row", "value", "result", "results",
    "count", "total", "average", "sum", "max", "min", "top", "bottom",
    "first", "last", "latest", "recent", "new", "old", "current",
    "name", "id", "number", "date", "year", "month", "day",
    "january", "february", "march", "april", "june", "july",
    "august", "september", "october", "november", "december",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "me", "us", "them", "him", "her", "his", "hers", "their", "our", "my",
    "she", "he", "they", "it", "its", "we", "i", "you", "your",
    "hosted", "created", "owned", "assigned", "managed", "led", "run",
    "region", "department", "category", "type", "status", "level",
}

# spaCy entity labels we care about as filter candidates.
# DATE, TIME, CARDINAL, ORDINAL, MONEY, QUANTITY, PERCENT are intentionally
# excluded — numeric/temporal values are handled by SQL directly and should
# not be validated against the value index.
_NER_LABELS = {"PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "WORK_OF_ART", "FAC", "LOC"}


# ── Strategy 1: Rule-based ─────────────────────────────────────────────────────

def _rule_based(question: str) -> List[Dict]:
    candidates = []
    seen: set = set()

    def _add(text: str, method: str, entity_type: str = "") -> None:
        t = text.strip()
        key = t.lower()
        if t and len(t) > 1 and key not in _QUESTION_STOPWORDS and key not in seen:
            seen.add(key)
            candidates.append({"text": t, "method": method, "entity_type": entity_type})

    # Quoted strings — highest priority, keep verbatim
    for m in _QUOTED.finditer(question):
        val = m.group(1) or m.group(2)
        if val:
            _add(val, "quoted")

    # Strip quoted spans so they don't double-match
    clean = _QUOTED.sub(" ", question)

    # Brand + product number runs — "Loctite 401", "Loctite 243 Threadlocker"
    # Must run before _TITLECASE so the full phrase is seen as one candidate.
    brand_spans: list = []
    for m in _BRAND_NUM.finditer(clean):
        _add(m.group(1), "rule_brand_num")
        brand_spans.append((m.start(), m.end()))

    def _in_brand_span(start: int, end: int) -> bool:
        return any(bs <= start and end <= be for bs, be in brand_spans)

    # Multi-word TitleCase runs — probable proper nouns (skip if already in a brand span)
    for m in _TITLECASE.finditer(clean):
        if not _in_brand_span(m.start(), m.end()):
            _add(m.group(1), "rule_titlecase")

    # Single capitalised words not already captured above
    # (only if not immediately after sentence punctuation — avoids sentence starters)
    for m in _SINGLE_CAP.finditer(clean):
        pos = m.start()
        before = clean[:pos].rstrip()
        if before and before[-1] not in ".!?":
            _add(m.group(1), "rule_single_cap")

    # Dates are intentionally excluded — numeric date strings are not English
    # words and should not be validated against the value index.

    return candidates


# ── Strategy 2: spaCy NER + noun chunks ───────────────────────────────────────

_NLP = None
_SPACY_TRIED = False


def _load_spacy():
    global _NLP, _SPACY_TRIED
    if _SPACY_TRIED:
        return _NLP
    _SPACY_TRIED = True
    try:
        import spacy  # noqa: F401
        try:
            import spacy
            _NLP = spacy.load("en_core_web_sm")
        except OSError:
            # Model not downloaded yet — try once
            import subprocess, sys
            result = subprocess.run(
                [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
                capture_output=True,
            )
            if result.returncode == 0:
                import spacy as _spacy
                _NLP = _spacy.load("en_core_web_sm")
    except Exception:
        _NLP = None
    return _NLP


def _spacy_extract(question: str) -> List[Dict]:
    nlp = _load_spacy()
    if nlp is None:
        return []

    doc = nlp(question)
    candidates = []
    seen: set = set()

    def _add(text: str, method: str, entity_type: str = "") -> None:
        t = text.strip()
        key = t.lower()
        if t and len(t) > 1 and key not in _QUESTION_STOPWORDS and key not in seen:
            seen.add(key)
            candidates.append({"text": t, "method": method, "entity_type": entity_type})

    # Named entities — highest confidence
    for ent in doc.ents:
        if ent.label_ in _NER_LABELS:
            _add(ent.text, "spacy_ner", ent.label_)

    # Noun chunks as fallback (lower priority)
    for chunk in doc.noun_chunks:
        # Prefer the root lemma if the chunk is just a determiner + noun
        text = chunk.text if len(chunk) > 1 else chunk.root.text
        _add(text, "spacy_noun_chunk", "NOUN_CHUNK")

    return candidates


# ── Combined public API ────────────────────────────────────────────────────────

_METHOD_PRIORITY = {
    "quoted":           0,
    "spacy_ner":        1,
    "rule_brand_num":   2,   # "Loctite 401" — brand + number combined
    "rule_titlecase":   3,
    "spacy_noun_chunk": 4,
    "rule_single_cap":  5,
}


def extract_filter_candidates(question: str) -> List[Dict]:
    """
    Extract potential filter values from a user question.

    Returns a deduplicated list of candidates, highest-priority first:

        [{"text": str, "method": str, "entity_type": str}, ...]

    ``text``        — the raw extracted string (e.g. "Tracy Wu")
    ``method``      — extraction method (e.g. "spacy_ner", "rule_titlecase")
    ``entity_type`` — NER label or "" (e.g. "PERSON", "ORG", "DATE", "")
    """
    seen: set = set()
    merged: List[Dict] = []

    for cand in [*_rule_based(question), *_spacy_extract(question)]:
        key = cand["text"].lower()
        if key not in seen:
            seen.add(key)
            merged.append(cand)

    merged.sort(key=lambda c: (_METHOD_PRIORITY.get(c["method"], 99),))
    return merged
