"""
rag/rag_verifier.py — 3-layer RAG answer verification.

Gate 1 — Product exists?        (pre-retrieval; uses index metadata)
Gate 2 — Relevant datasheet?    (post-retrieval; uses chunk scores)
Gate 3 — Answer grounded?       (post-generation; compares answer claims to chunks)

Layers 1 and 2 are hard gates: failure returns a grounded refusal and
the pipeline stops.  Layer 3 is a soft gate: failure prepends a caveat
to the answer rather than refusing it entirely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Thresholds ────────────────────────────────────────────────────────────────

MIN_RETRIEVAL_SCORE = 0.05   # below this, top chunk is essentially noise
MIN_GROUNDING_RATE  = 0.30   # fraction of answer numbers that must appear in context


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class VerificationLayer:
    layer:   int
    name:    str
    passed:  bool
    score:   float = 1.0   # 0–1 confidence
    detail:  str   = ""    # human-readable diagnosis
    refusal: str   = ""    # surface this when the layer fails


@dataclass
class RAGVerificationResult:
    passed:          bool
    failed_layer:    int                      # 0 = all passed
    layers:          list[VerificationLayer]  = field(default_factory=list)
    refusal_message: str                      = ""   # hard-stop (layers 1/2)
    warning_message: str                      = ""   # soft-warn (layer 3)

    def to_dict(self) -> dict:
        return {
            "passed":       self.passed,
            "failed_layer": self.failed_layer,
            "layers": [
                {
                    "layer":   l.layer,
                    "name":    l.name,
                    "passed":  l.passed,
                    "score":   round(l.score, 3),
                    "detail":  l.detail,
                }
                for l in self.layers
            ],
        }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_product_codes(text: str) -> list[str]:
    """
    Extract product codes from LOCTITE mentions (e.g. '243', '401A', '243B').
    Codes always start with a digit — this prevents common English words like
    'products', 'adhesive', 'threadlocker' from being matched as product codes.
    """
    return [m.upper() for m in re.findall(r'LOCTITE\s+(\d[\dA-Z]*)', text, re.IGNORECASE)]


def _extract_numbers(text: str) -> set[str]:
    """
    All numeric tokens (integers and decimals) in a string, normalised so that
    trivial formatting differences don't cause false mismatches:
      0.700  →  0.7      (trailing zeros stripped)
      24.0   →  24       (integer-valued floats collapsed)
      007    →  7        (leading zeros stripped)
    """
    raw = re.findall(r'\b\d+(?:\.\d+)?\b', text)
    normalised = set()
    for n in raw:
        try:
            f = float(n)
            # Represent as int if it has no fractional part
            normalised.add(str(int(f)) if f == int(f) else str(f))
        except ValueError:
            normalised.add(n)
    return normalised


def _extract_loctite_names(text: str) -> set[str]:
    """Lowercased full LOCTITE product names (e.g. 'loctite 243') from text."""
    return {m.lower() for m in re.findall(r'LOCTITE\s+\d[\dA-Z]*', text, re.IGNORECASE)}


# ── Gate 1: Product exists in index? ─────────────────────────────────────────

def verify_product_exists(
    question: str,
    known_product_ids: set[str],
    product_index=None,
) -> VerificationLayer:
    """
    Check that each LOCTITE product mentioned in the question is known to
    the system — either in the RAG documentation index or the SQL product index.

    Two-stage lookup per product code:
      1. FAISS docs   — known_product_ids from HybridRetriever.known_product_ids
      2. Product index — product_index.resolve() covers DB products whose
                         datasheet may not yet be in the RAG index.

    Passes automatically when:
      - the question names no specific LOCTITE product, OR
      - all named products are found by either lookup.
    """
    codes = _extract_product_codes(question)

    if not codes:
        return VerificationLayer(
            layer=1, name="product_exists",
            passed=True, score=1.0,
            detail="no specific product named — general question",
        )

    missing: list[str] = []
    sources: list[str] = []

    for code in codes:
        code_lower = code.lower()

        # Stage 1: RAG documentation index
        in_docs = any(code_lower in pid for pid in known_product_ids)

        # Stage 2: product inverted index (SQL DB side)
        in_db = False
        if not in_docs and product_index is not None:
            try:
                if product_index.is_ready():
                    canonical = (
                        product_index.resolve(f"LOCTITE {code}")
                        or product_index.resolve(code)
                    )
                    in_db = canonical is not None
            except Exception:
                pass

        if in_docs or in_db:
            sources.append(f"{code}({'docs' if in_docs else 'db'})")
        else:
            missing.append(code)

    if missing:
        missing_str = ", ".join(f"LOCTITE {c}" for c in missing)
        return VerificationLayer(
            layer=1, name="product_exists",
            passed=False, score=0.0,
            detail=f"not found in docs or db: {missing_str}",
            refusal=(
                f"**{missing_str}** could not be found in the product "
                "documentation or the database. Please verify the product "
                "name, or contact your Loctite representative for products "
                "not yet in the knowledge base."
            ),
        )

    return VerificationLayer(
        layer=1, name="product_exists",
        passed=True, score=1.0,
        detail=f"confirmed: {', '.join(sources)}",
    )


# ── Gate 2: Relevant datasheet retrieved? ─────────────────────────────────────

def verify_retrieval_quality(
    question: str,
    chunks: list[dict],
) -> VerificationLayer:
    """
    Check that retrieval returned at least one chunk whose score clears
    the minimum relevance threshold.

    chunks  — list of {"text": str, "score": float, "source": str, ...}
    """
    if not chunks:
        return VerificationLayer(
            layer=2, name="retrieval_quality",
            passed=False, score=0.0,
            detail="retrieval returned 0 chunks",
            refusal=(
                "No relevant documentation was found for your question. "
                "The information may not yet be available in the knowledge base."
            ),
        )

    top_score = max(c.get("score", 0.0) for c in chunks)
    sources   = sorted({c.get("source", "") for c in chunks if c.get("source")})

    if top_score < MIN_RETRIEVAL_SCORE:
        return VerificationLayer(
            layer=2, name="retrieval_quality",
            passed=False, score=top_score,
            detail=f"top score {top_score:.3f} < threshold {MIN_RETRIEVAL_SCORE}",
            refusal=(
                "The available documentation does not appear to contain "
                f"relevant information for this question (best match score: {top_score:.2f}). "
                "Please try rephrasing your question or ask about a specific product."
            ),
        )

    return VerificationLayer(
        layer=2, name="retrieval_quality",
        passed=True, score=top_score,
        detail=(
            f"top score {top_score:.3f}, {len(chunks)} chunk(s) from "
            f"{', '.join(sources[:3])}"
        ),
    )


# ── Gate 3: Answer supported by retrieved evidence? ───────────────────────────

def verify_answer_grounding(
    answer: str,
    chunks: list[dict],
) -> VerificationLayer:
    """
    Check that numeric values and product names cited in the final answer
    are actually present in the retrieved chunk text.

    Grounding score = mean of:
      - numeric_score   : fraction of answer numbers found in context
      - product_score   : fraction of answer LOCTITE names found in context

    If either source has nothing to check (no numbers, no product names) its
    component defaults to 1.0 (not penalised).

    A score below MIN_GROUNDING_RATE issues a soft-warning; the caller
    should prepend layer.refusal to the answer rather than replacing it.
    """
    if not chunks:
        return VerificationLayer(
            layer=3, name="answer_grounding",
            passed=False, score=0.0,
            detail="no chunks to check against",
            refusal=(
                "*Note: this answer was generated without retrieved documentation "
                "and may contain unverified information.*\n\n"
            ),
        )

    context = " ".join(c.get("text", "") for c in chunks)

    # Numeric grounding
    answer_nums  = _extract_numbers(answer)
    context_nums = _extract_numbers(context)
    if answer_nums:
        grounded_nums  = answer_nums & context_nums
        num_score      = len(grounded_nums) / len(answer_nums)
        ungrounded_nums = sorted(answer_nums - context_nums)
    else:
        num_score       = 1.0
        ungrounded_nums = []

    # Product name grounding
    answer_products  = _extract_loctite_names(answer)
    context_products = _extract_loctite_names(context)
    if answer_products:
        prod_score = len(answer_products & context_products) / len(answer_products)
    else:
        prod_score = 1.0

    overall = (num_score + prod_score) / 2

    if overall < MIN_GROUNDING_RATE:
        detail = (
            f"grounding {overall:.2f} "
            f"(numbers {num_score:.2f}, products {prod_score:.2f})"
        )
        if ungrounded_nums:
            detail += f"; unverified values: {ungrounded_nums[:5]}"

        return VerificationLayer(
            layer=3, name="answer_grounding",
            passed=False, score=overall,
            detail=detail,
            refusal=(
                "*Note: parts of this answer could not be directly verified "
                "against the retrieved documentation. "
                "Please cross-check important figures with the official datasheet.*\n\n"
            ),
        )

    return VerificationLayer(
        layer=3, name="answer_grounding",
        passed=True, score=overall,
        detail=(
            f"grounding {overall:.2f} "
            f"(numbers {num_score:.2f}, products {prod_score:.2f})"
        ),
    )
