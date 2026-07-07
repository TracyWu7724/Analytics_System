"""
entity_matcher.py — Query-time entity matching using the hybrid value index.

Given a raw candidate string extracted from a user question, this module:
  1. Runs the fast InvertedIndex lookup.
  2. If the result is ambiguous (below FOUND_THRESHOLD but above SUGGEST_THRESHOLD),
     asks an LLM judge to pick the best match.
  3. Returns a structured MatchDecision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

FOUND_THRESHOLD   = 0.72
SUGGEST_THRESHOLD = 0.45


@dataclass
class MatchDecision:
    original:   str
    matched:    Optional[str]   # canonical value from the index (or None)
    table:      Optional[str]
    col:        Optional[str]
    confidence: float
    method:     str             # "exact" | "fuzzy" | "llm_judge" | "none"
    found:      bool


def match_entity(
    candidate: str,
    value_index,              # InvertedIndex or HybridValueIndex
    table: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> MatchDecision:
    """
    Resolve `candidate` against the value index.

    Falls back to an LLM judge when the fuzzy score is in the ambiguous range.
    """
    if value_index is None or not candidate.strip():
        return MatchDecision(
            original=candidate, matched=None, table=None, col=None,
            confidence=0.0, method="none", found=False,
        )

    result = value_index.search_value(candidate, table=table)

    if result.exact:
        m = result.top_matches[0]
        return MatchDecision(
            original=candidate,
            matched=m["value"], table=m["table"], col=m["col"],
            confidence=1.0, method="exact", found=True,
        )

    if result.found:
        m = result.top_matches[0]
        return MatchDecision(
            original=candidate,
            matched=m["value"], table=m["table"], col=m["col"],
            confidence=result.confidence, method="fuzzy", found=True,
        )

    if result.confidence >= SUGGEST_THRESHOLD and result.top_matches and llm_model:
        decision = _llm_judge(candidate, result.top_matches[:5], llm_model)
        if decision:
            return MatchDecision(
                original=candidate,
                matched=decision["value"], table=decision["table"], col=decision["col"],
                confidence=result.confidence, method="llm_judge", found=True,
            )

    return MatchDecision(
        original=candidate, matched=None, table=None, col=None,
        confidence=result.confidence, method="none", found=False,
    )


def _llm_judge(
    candidate: str,
    candidates: list[dict],
    llm_model: str,
) -> Optional[dict]:
    """
    Ask the LLM whether `candidate` refers to any of the top index candidates.
    Returns the best-matching candidate dict, or None if no match.
    """
    try:
        from ..generation.llm_registry import get_llm
        llm = get_llm(llm_model)

        options = "\n".join(
            f"  {i+1}. {c['value']}  (table={c['table']}, col={c['col']})"
            for i, c in enumerate(candidates)
        )
        prompt = (
            f"A user query contains the entity: \"{candidate}\"\n\n"
            f"The following values exist in the database:\n{options}\n\n"
            f"Does the user entity refer to one of these database values? "
            f"Reply with just the number (1-{len(candidates)}) of the best match, "
            f"or 0 if none match. No explanation."
        )

        response = llm.invoke(prompt)
        text = response.content.strip() if hasattr(response, "content") else str(response).strip()
        idx = int(text.split()[0]) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]
    except Exception as exc:
        logger.debug(f"[EntityMatcher] LLM judge failed for '{candidate}': {exc}")
    return None
