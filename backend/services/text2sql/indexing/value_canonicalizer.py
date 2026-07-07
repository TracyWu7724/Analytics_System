"""
value_canonicalizer.py — Normalize raw DB values to canonical forms.

The goal is to make "LOCTITE 243", "loctite-243", "Loctite243" all
map to the same index entry so the hallucination guard can find them
regardless of which spelling the LLM uses.
"""

from __future__ import annotations

import re

# Map of common abbreviations → canonical expansions.
# Keep entries lowercase; matching is case-insensitive.
CANONICAL_MAP: dict[str, str] = {
    "n/a":     "not available",
    "na":      "not available",
    "tbd":     "to be determined",
    "qty":     "quantity",
    "pcs":     "pieces",
    "ea":      "each",
    "yr":      "year",
    "mo":      "month",
    "wk":      "week",
    "dept":    "department",
    "mgr":     "manager",
    "prod":    "product",
    "mfr":     "manufacturer",
    "mfg":     "manufacturing",
    "dist":    "distribution",
    "inv":     "inventory",
    "ord":     "order",
    "rev":     "revenue",
    "amt":     "amount",
    "vol":     "volume",
    "avg":     "average",
    "max":     "maximum",
    "min":     "minimum",
    "std":     "standard",
}

_SEPARATORS = re.compile(r"[-_/\\|]+")


def canonicalize(value: str) -> str:
    """
    Return a canonical, lowercase string for `value`.

    Steps:
    1. Lowercase and strip whitespace.
    2. Normalize separator characters (-, _, /) to spaces.
    3. Collapse whitespace.
    4. Expand known abbreviations.
    """
    v = value.strip().lower()
    v = _SEPARATORS.sub(" ", v)
    v = re.sub(r"\s+", " ", v).strip()

    words = v.split()
    words = [CANONICAL_MAP.get(w, w) for w in words]
    return " ".join(words)


def canonical_variants(value: str) -> list[str]:
    """Return [original_lowercase, canonical] — deduped."""
    original = value.strip().lower()
    canon = canonicalize(value)
    seen: list[str] = [original]
    if canon != original:
        seen.append(canon)
    return seen
