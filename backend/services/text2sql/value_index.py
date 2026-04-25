"""
value_index.py — IR-based distinct-value index for Databricks string columns.

Indexing
--------
  Hash table per (table, column) — O(1) add/remove/lookup.
  Populated at startup via background thread; callable for incremental refresh.

Search pipeline (at query time)
--------------------------------
  Stage 1 — Exact (hash lookup, case-insensitive)
  Stage 2 — BM25 keyword prefilter  (rank_bm25)
  Stage 3 — Embedding cosine similarity  (sentence-transformers, on BM25 top-k)
  Stage 4 — Confidence threshold gating
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── Type aliases ───────────────────────────────────────────────────────────────
_Store     = Dict[str, Dict[str, Dict[str, str]]]          # table → col → hash → value
_BM25Key   = Tuple[str, str]
_EmbKey    = Tuple[str, str]

# ── Tuning constants ───────────────────────────────────────────────────────────
MAX_PER_COL       = 300    # DISTINCT values to fetch per column
BM25_TOP_K        = 20     # candidates passed to embedding stage
FOUND_THRESHOLD   = 0.72   # combined confidence → "found"
SUGGEST_THRESHOLD = 0.45   # combined confidence → "possible match"
BM25_WEIGHT       = 0.35
EMB_WEIGHT        = 0.65

# Databricks column types treated as "string" (index these)
_STRING_TYPES = {
    "string", "varchar", "char", "text", "nvarchar", "nchar",
    "clob", "tinytext", "mediumtext", "longtext",
}


def _is_string_col(col_type: str) -> bool:
    base = col_type.lower().split("(")[0].strip()
    return base in _STRING_TYPES


def _hash_val(v: str) -> str:
    """12-char SHA-1 hash of a lowercased value — used as the hash-map key."""
    return hashlib.sha1(v.lower().encode("utf-8")).hexdigest()[:12]


def _tokenize(text: str) -> List[str]:
    """Split on non-alphanumeric, lowercase, drop empty tokens."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


# ── Result type ────────────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    query:       str
    found:       bool          # True  → confident match exists
    exact:       bool          # True  → exact case-insensitive match
    confidence:  float         # 0.0 – 1.0
    top_matches: List[Dict] = field(default_factory=list)
    # Each match: {"table", "col", "value", "bm25", "emb", "confidence"}


# ── ValueIndex ─────────────────────────────────────────────────────────────────

class ValueIndex:
    """
    Hash-indexed store of distinct string column values with a 4-stage IR pipeline.
    Thread-safe; the background build thread writes under a lock.
    """

    def __init__(self, embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self._store:       _Store                        = {}
        self._bm25_cache:  Dict[_BM25Key, tuple]        = {}   # key → (values, BM25Okapi)
        self._emb_cache:   Dict[_EmbKey,  tuple]        = {}   # key → (values, np.ndarray)
        self._dirty:       set                           = set()
        self._embed_model_name = embed_model_name
        self._embed_model  = None
        self._lock         = threading.RLock()
        self._built        = False

    # ── Build / refresh ────────────────────────────────────────────────────────

    def build(self, data_service, background: bool = True) -> None:
        """Scan all Databricks tables and populate the index."""
        if background:
            t = threading.Thread(
                target=self._build_sync, args=(data_service,), daemon=True
            )
            t.start()
        else:
            self._build_sync(data_service)

    def _build_sync(self, data_service) -> None:
        try:
            tables = data_service.get_table_names()
            logger.info(f"[ValueIndex] Indexing {len(tables)} table(s) in background…")
            for table in tables:
                self._index_table(table, data_service)
            with self._lock:
                self._built = True
            total_cols = sum(len(c) for c in self._store.values())
            logger.info(f"[ValueIndex] Ready — {total_cols} column(s) indexed across {len(self._store)} table(s)")
        except Exception as exc:
            logger.error(f"[ValueIndex] Build failed: {exc}")

    def _index_table(self, table: str, data_service) -> None:
        """Fetch and store DISTINCT values for every string column in one table."""
        try:
            schema = data_service.get_table_schema(table)
        except Exception:
            return
        for col_info in schema:
            col_name = col_info.get("name", "")
            col_type = col_info.get("type", "")
            if col_name and _is_string_col(col_type):
                self._index_column(table, col_name, data_service)

    def _index_column(self, table: str, col: str, data_service) -> None:
        try:
            rows = data_service.execute_query(
                f"SELECT DISTINCT `{col}` FROM {table} WHERE `{col}` IS NOT NULL",
                custom_limit=MAX_PER_COL,
            )
            vals = [
                str(r.get(col, "")).strip().lower()
                for r in rows
                if r.get(col) is not None and str(r.get(col, "")).strip()
            ]
            if not vals:
                return
            with self._lock:
                self._store.setdefault(table, {})[col] = {_hash_val(v): v for v in vals}
                self._dirty.add((table, col))
            logger.debug(f"[ValueIndex] {table}.{col}: {len(vals)} distinct values")
        except Exception as exc:
            logger.debug(f"[ValueIndex] Skipped {table}.{col}: {exc}")

    # ── Incremental update (O(1)) ──────────────────────────────────────────────

    def add_value(self, table: str, col: str, value: str) -> None:
        """Insert a single value into the hash map and invalidate caches."""
        with self._lock:
            value = value.strip().lower()
            self._store.setdefault(table, {}).setdefault(col, {})[_hash_val(value)] = value
            self._invalidate(table, col)

    def remove_value(self, table: str, col: str, value: str) -> None:
        """Remove a single value from the hash map and invalidate caches."""
        with self._lock:
            self._store.get(table, {}).get(col, {}).pop(_hash_val(value), None)
            self._invalidate(table, col)

    def refresh_table(self, table: str, data_service) -> None:
        """Re-index all string columns for one table (e.g. after a data refresh)."""
        self._index_table(table, data_service)

    def _invalidate(self, table: str, col: str) -> None:
        key = (table, col)
        self._bm25_cache.pop(key, None)
        self._emb_cache.pop(key, None)
        self._dirty.add(key)

    # ── Lazy index builders ────────────────────────────────────────────────────

    def _get_values(self, table: str, col: str) -> List[str]:
        return list(self._store.get(table, {}).get(col, {}).values())

    def _get_bm25(self, table: str, col: str):
        """Return (values, BM25Okapi) — built lazily, cached per column."""
        key = (table, col)
        with self._lock:
            if key not in self._bm25_cache:
                vals = self._get_values(table, col)
                try:
                    from rank_bm25 import BM25Okapi
                    corpus = [_tokenize(v) for v in vals]
                    bm25   = BM25Okapi(corpus) if corpus else None
                except ImportError:
                    bm25 = None
                self._bm25_cache[key] = (vals, bm25)
        return self._bm25_cache[key]

    def _get_emb_matrix(self, table: str, col: str):
        """
        Return (values, embedding_matrix) — built lazily, cached per column.
        matrix shape: (n_values, emb_dim), normalized.
        """
        key = (table, col)
        with self._lock:
            if key not in self._emb_cache:
                vals = self._get_values(table, col)
                mat  = None
                if vals:
                    try:
                        model = self._load_embed_model()
                        mat   = model.encode(vals, normalize_embeddings=True,
                                             show_progress_bar=False, batch_size=64)
                    except Exception as exc:
                        logger.debug(f"[ValueIndex] Embedding build failed for {key}: {exc}")
                self._emb_cache[key] = (vals, mat)
        return self._emb_cache[key]

    def _load_embed_model(self):
        if self._embed_model is None:
            from sentence_transformers import SentenceTransformer
            self._embed_model = SentenceTransformer(self._embed_model_name)
        return self._embed_model

    # ── 4-Stage search pipeline ────────────────────────────────────────────────

    def search(self, candidate: str, table: Optional[str] = None) -> SearchResult:
        """
        Run the full IR pipeline for a single candidate string.

        Parameters
        ----------
        candidate : str
            The value to look up (e.g. "Tracy Wu").
        table : str, optional
            Restrict search to a specific fully-qualified table name.

        Returns
        -------
        SearchResult
        """
        if not self._built or not candidate.strip():
            return SearchResult(query=candidate, found=False, exact=False, confidence=0.0)

        cand_clean = candidate.strip().lower()
        h           = _hash_val(cand_clean)

        # Narrow scope to one table if specified
        if table and table in self._store:
            tables_to_search = {table: self._store[table]}
        else:
            tables_to_search = dict(self._store)

        # ── Stage 1: Exact hash lookup ─────────────────────────────────────────
        exact_hits = []
        for tbl, cols in tables_to_search.items():
            for col, hmap in cols.items():
                if h in hmap:
                    exact_hits.append({
                        "table": tbl, "col": col, "value": hmap[h],
                        "bm25": 1.0, "emb": 1.0, "confidence": 1.0,
                    })
        if exact_hits:
            return SearchResult(
                query=cand_clean, found=True, exact=True,
                confidence=1.0, top_matches=exact_hits,
            )

        # ── Stage 2: BM25 keyword prefilter ───────────────────────────────────
        query_tokens = _tokenize(cand_clean)
        if not query_tokens:
            return SearchResult(query=cand_clean, found=False, exact=False, confidence=0.0)

        # Collect (tbl, col, val_idx, bm25_score) for top-k per column
        bm25_hits: List[Tuple[str, str, int, float]] = []

        for tbl, cols in tables_to_search.items():
            for col in cols:
                vals, bm25 = self._get_bm25(tbl, col)
                if bm25 is None or not vals:
                    continue
                scores    = bm25.get_scores(query_tokens)
                if scores.max() < 0.01:
                    continue
                top_idx   = np.argsort(scores)[::-1][:BM25_TOP_K]
                for idx in top_idx:
                    if float(scores[idx]) > 0.01:
                        bm25_hits.append((tbl, col, int(idx), float(scores[idx])))

        if not bm25_hits:
            return SearchResult(query=cand_clean, found=False, exact=False, confidence=0.0)

        max_bm25 = max(h[3] for h in bm25_hits)

        # ── Stage 3: Embedding similarity (on BM25 top-k only) ───────────────
        try:
            model     = self._load_embed_model()
            query_emb = model.encode([cand_clean], normalize_embeddings=True)[0]
        except Exception:
            query_emb = None

        matches = []
        seen: set = set()

        for tbl, col, val_idx, bm25_score in bm25_hits:
            vals, emb_mat = self._get_emb_matrix(tbl, col)
            if val_idx >= len(vals):
                continue
            val = vals[val_idx]
            key = (tbl, col, val.lower())
            if key in seen:
                continue
            seen.add(key)

            norm_bm25 = bm25_score / max_bm25

            emb_sim = 0.0
            if query_emb is not None and emb_mat is not None and val_idx < len(emb_mat):
                emb_sim = float(np.dot(emb_mat[val_idx], query_emb))

            # ── Stage 4: Confidence scoring ───────────────────────────────────
            confidence = BM25_WEIGHT * norm_bm25 + EMB_WEIGHT * max(emb_sim, 0.0)

            matches.append({
                "table": tbl, "col": col, "value": val,
                "bm25":  round(norm_bm25, 3),
                "emb":   round(emb_sim, 3),
                "confidence": round(confidence, 3),
            })

        matches.sort(key=lambda x: x["confidence"], reverse=True)
        top5 = matches[:5]
        best  = top5[0]["confidence"] if top5 else 0.0

        return SearchResult(
            query=cand_clean,
            found=best >= FOUND_THRESHOLD,
            exact=False,
            confidence=best,
            top_matches=top5,
        )

    # ── Utilities ──────────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        return self._built

    def get_samples(self, table: str, col: str, n: int = 5) -> List[str]:
        """Return up to n sample values for a specific column."""
        return list(self._store.get(table, {}).get(col, {}).values())[:n]

    def column_summary(self) -> Dict[str, int]:
        """Return {table.col: value_count} for all indexed columns."""
        out = {}
        for tbl, cols in self._store.items():
            for col, hmap in cols.items():
                out[f"{tbl}.{col}"] = len(hmap)
        return out


# ── Module-level singleton ─────────────────────────────────────────────────────

_instance: Optional[ValueIndex] = None


def init_value_index(
    data_service,
    embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    background: bool = True,
) -> ValueIndex:
    global _instance
    _instance = ValueIndex(embed_model_name=embed_model_name)
    _instance.build(data_service, background=background)
    return _instance


def get_value_index() -> Optional[ValueIndex]:
    return _instance
