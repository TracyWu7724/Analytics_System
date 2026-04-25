"""
inverted_index.py — Persistent inverted index for Databricks schema + distinct values
                    + historical question→table mappings.

Three indexes, all saved to disk as JSON:

  schema_index.json
    token → [(table, col), ...]
    Built from column names of every table.
    Used by table_matching to boost tables whose columns match the question.

  value_index.json
    token → [(table, col, original_value), ...]
    Built from DISTINCT values of every string column.
    Used by the hallucination guard to verify filter values exist before SQL runs.

  history_index.json
    token → [(question, table, timestamp), ...]
    Grown organically: every successful SQL query appends here.
    Used by table_matching to boost tables that answered similar past questions.

Lookup pipeline (at query time):
  1. Tokenise candidate
  2. Intersect each token with posting lists  →  candidate (table, col, value) set
  3. Score by token overlap ratio
  4. Embedding cosine similarity reranks top-k  (sentence-transformers, lazy)
  5. Confidence threshold gates the result

Persistence:
  - Loaded from disk on startup (milliseconds)
  - Rebuilt from Databricks only when stale (default TTL: 24 h) or manually triggered
  - Incremental add / remove in O(1) per token via hash-keyed posting lists
  - History grows incrementally; never erased by rebuild
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
INDEX_VERSION   = 2
MAX_AGE_HOURS   = 24          # rebuild if index is older than this
MAX_PER_COL     = 300         # max DISTINCT values fetched per column
EMB_TOP_K       = 10          # candidates passed to embedding reranker
FOUND_THRESHOLD = 0.72        # combined score → "found"
SUGGEST_THRESHOLD = 0.45      # combined score → "possible match"
MAX_HISTORY_PER_TOKEN = 200   # cap posting list per token to avoid unbounded growth

_STRING_TYPES = {
    "string", "varchar", "char", "text", "nvarchar", "nchar",
    "clob", "tinytext", "mediumtext", "longtext",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_string_col(col_type: str) -> bool:
    return col_type.lower().split("(")[0].strip() in _STRING_TYPES


def _tokenise(text: str) -> List[str]:
    """Lowercase, split on non-alphanumeric, drop single chars."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 1]


def _val_hash(value: str) -> str:
    """8-char hash used as a set-membership key (case-insensitive)."""
    return hashlib.sha1(value.lower().encode()).hexdigest()[:8]


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    query:       str
    found:       bool
    exact:       bool
    confidence:  float
    top_matches: List[Dict] = field(default_factory=list)
    # each match: {table, col, value, token_score, emb_score, confidence}


# ── Main class ────────────────────────────────────────────────────────────────

class InvertedIndex:
    """
    Dual persistent inverted index (schema + values) with embedding reranking.
    Thread-safe; background build/reload never blocks the request path.
    """

    def __init__(
        self,
        index_dir: str = "",
        embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        max_age_hours: int = MAX_AGE_HOURS,
    ):
        self._dir     = Path(index_dir) if index_dir else Path(__file__).resolve().parents[3] / "index"
        self._dir.mkdir(parents=True, exist_ok=True)

        self._schema_path  = self._dir / "schema_index.json"
        self._value_path   = self._dir / "value_index.json"
        self._meta_path    = self._dir / "index_meta.json"
        self._history_path = self._dir / "history_index.json"

        # In-memory posting lists
        # schema: token → [(table, col), ...]
        self._schema: Dict[str, List[Tuple[str, str]]]             = {}
        # values: token → [(table, col, original_value), ...]
        self._values: Dict[str, List[Tuple[str, str, str]]]        = {}
        # exact lookup: hash → (table, col, value)
        self._exact:  Dict[str, Tuple[str, str, str]]              = {}
        # history: token → [(question, table, timestamp), ...]
        self._history: Dict[str, List[Tuple[str, str, str]]]       = {}

        self._embed_model_name = embed_model_name
        self._embed_model      = None
        self._max_age          = timedelta(hours=max_age_hours)
        self._lock             = threading.RLock()
        self._ready            = False

    # ── Startup ───────────────────────────────────────────────────────────────

    def load_or_build(self, data_service, background: bool = True) -> None:
        """
        Try to load from disk.  If missing or stale, rebuild from Databricks.
        Safe to call at server startup.
        """
        if self._load_from_disk():
            logger.info(f"[Index] Loaded from disk ({self._schema_path.parent})")
            self._ready = True
            # If stale, kick off a background refresh
            if self._is_stale():
                logger.info("[Index] Stale — refreshing in background")
                self._start_build(data_service)
        else:
            logger.info("[Index] Not found or incompatible — building from Databricks")
            self._start_build(data_service, background=background)

    def _start_build(self, data_service, background: bool = True) -> None:
        if background:
            t = threading.Thread(target=self._build_sync, args=(data_service,), daemon=True)
            t.start()
        else:
            self._build_sync(data_service)

    # ── Disk I/O ──────────────────────────────────────────────────────────────

    def _load_from_disk(self) -> bool:
        try:
            if not (self._schema_path.exists() and self._value_path.exists() and self._meta_path.exists()):
                return False
            meta = json.loads(self._meta_path.read_text())
            if meta.get("version") != INDEX_VERSION:
                return False
            schema_data = json.loads(self._schema_path.read_text())
            value_data  = json.loads(self._value_path.read_text())
            with self._lock:
                self._schema = {k: [tuple(p) for p in v] for k, v in schema_data.items()}
                self._values = {k: [tuple(p) for p in v] for k, v in value_data.items()}
                self._rebuild_exact()
            # History is loaded separately — always preserved even when schema/value index rebuilds
            self._load_history_from_disk()
            return True
        except Exception as exc:
            logger.warning(f"[Index] Failed to load from disk: {exc}")
            return False

    def _load_history_from_disk(self) -> None:
        """Load history index from disk. Silently no-ops if file is missing."""
        try:
            if self._history_path.exists():
                history_data = json.loads(self._history_path.read_text())
                with self._lock:
                    self._history = {k: [tuple(p) for p in v] for k, v in history_data.items()}
                logger.debug(f"[Index] History loaded: {len(self._history)} tokens")
        except Exception as exc:
            logger.warning(f"[Index] Failed to load history from disk: {exc}")

    def _save_to_disk(self) -> None:
        try:
            with self._lock:
                schema_data = {k: [list(p) for p in v] for k, v in self._schema.items()}
                value_data  = {k: [list(p) for p in v] for k, v in self._values.items()}

            self._schema_path.write_text(json.dumps(schema_data, ensure_ascii=False))
            self._value_path.write_text(json.dumps(value_data,  ensure_ascii=False))
            self._meta_path.write_text(json.dumps({
                "version":  INDEX_VERSION,
                "built_at": datetime.utcnow().isoformat(),
                "tables":   self._indexed_tables(),
            }, ensure_ascii=False))
            logger.info(f"[Index] Saved to {self._dir}")
        except Exception as exc:
            logger.error(f"[Index] Failed to save to disk: {exc}")

    def _save_history_to_disk(self) -> None:
        try:
            with self._lock:
                history_data = {k: [list(p) for p in v] for k, v in self._history.items()}
            self._history_path.write_text(json.dumps(history_data, ensure_ascii=False))
        except Exception as exc:
            logger.error(f"[Index] Failed to save history to disk: {exc}")

    def _is_stale(self) -> bool:
        try:
            meta = json.loads(self._meta_path.read_text())
            built_at = datetime.fromisoformat(meta["built_at"])
            return datetime.utcnow() - built_at > self._max_age
        except Exception:
            return True

    def _indexed_tables(self) -> List[str]:
        tables: set = set()
        for postings in self._schema.values():
            for tbl, _ in postings:
                tables.add(tbl)
        return sorted(tables)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_sync(self, data_service) -> None:
        """Fetch all table schemas + distinct values and build both indexes."""
        new_schema: Dict[str, List[Tuple[str, str]]]          = {}
        new_values: Dict[str, List[Tuple[str, str, str]]]     = {}
        new_exact:  Dict[str, Tuple[str, str, str]]           = {}

        try:
            tables = data_service.get_table_names()
            logger.info(f"[Index] Building from {len(tables)} table(s)…")

            for table in tables:
                try:
                    schema = data_service.get_table_schema(table)
                except Exception:
                    continue

                for col_info in schema:
                    col_name = col_info.get("name", "")
                    col_type = col_info.get("type", "")
                    if not col_name:
                        continue

                    # ── Schema index (column names) ──────────────────────────
                    for tok in _tokenise(col_name):
                        new_schema.setdefault(tok, []).append((table, col_name))

                    # ── Value index (distinct string values) ─────────────────
                    if not _is_string_col(col_type):
                        continue

                    try:
                        rows = data_service.execute_query(
                            f"SELECT DISTINCT `{col_name}` FROM {table} "
                            f"WHERE `{col_name}` IS NOT NULL",
                            custom_limit=MAX_PER_COL,
                        )
                        for row in rows:
                            val = str(row.get(col_name, "")).strip().lower()
                            if not val:
                                continue
                            # Exact hash
                            h = _val_hash(val)
                            new_exact[h] = (table, col_name, val)
                            # Token postings
                            for tok in _tokenise(val):
                                posting = (table, col_name, val)
                                lst = new_values.setdefault(tok, [])
                                if posting not in lst:   # dedup within token list
                                    lst.append(posting)

                        logger.debug(f"[Index] {table}.{col_name}: {len(rows)} values")
                    except Exception as exc:
                        logger.debug(f"[Index] Skipped values for {table}.{col_name}: {exc}")

            with self._lock:
                self._schema = new_schema
                self._values = new_values
                self._exact  = new_exact
                self._ready  = True

            self._save_to_disk()
            # Reload history so it isn't lost when schema/value index rebuilds
            self._load_history_from_disk()
            logger.info(
                f"[Index] Done — {len(new_schema)} schema tokens, "
                f"{len(new_values)} value tokens across {len(tables)} tables"
            )

        except Exception as exc:
            logger.error(f"[Index] Build failed: {exc}")

    def _rebuild_exact(self) -> None:
        """Reconstruct the exact-hash map from the value postings."""
        self._exact = {}
        for postings in self._values.values():
            for tbl, col, val in postings:
                h = _val_hash(val)
                if h not in self._exact:
                    self._exact[h] = (tbl, col, val)

    # ── Incremental update (O(tokens)) ────────────────────────────────────────

    def add_value(self, table: str, col: str, value: str) -> None:
        """Insert a single value and persist the updated index."""
        value = value.strip().lower()
        with self._lock:
            h = _val_hash(value)
            self._exact[h] = (table, col, value)
            for tok in _tokenise(value):
                posting = (table, col, value)
                lst = self._values.setdefault(tok, [])
                if posting not in lst:
                    lst.append(posting)
        self._save_to_disk()

    def remove_value(self, table: str, col: str, value: str) -> None:
        """Remove a single value and persist the updated index."""
        with self._lock:
            self._exact.pop(_val_hash(value), None)
            posting = (table, col, value)
            for tok in _tokenise(value):
                self._values.get(tok, [])  # touch to avoid KeyError
                try:
                    self._values[tok].remove(posting)
                except (KeyError, ValueError):
                    pass
        self._save_to_disk()

    def rebuild(self, data_service, background: bool = True) -> None:
        """Force a full rebuild (e.g. after a Databricks data refresh)."""
        self._start_build(data_service, background=background)

    # ── Schema search (for table matching) ────────────────────────────────────

    def score_tables_by_schema(self, question: str) -> Dict[str, float]:
        """
        Return {table_full_name: score} based on how many question tokens
        match column names in that table.

        Score per table = Σ (1 + 2 × exact_col_match) for each matching token.
        Capped at 60 to blend with the fuzzy table-name score in table_matching.
        """
        if not self._ready:
            return {}

        tokens = _tokenise(question)
        table_scores: Dict[str, float] = {}

        with self._lock:
            for tok in tokens:
                for tbl, col in self._schema.get(tok, []):
                    col_toks = set(_tokenise(col))
                    # Exact column name match scores higher
                    bonus = 2.0 if tok in col_toks else 1.0
                    table_scores[tbl] = table_scores.get(tbl, 0.0) + bonus

        # Normalise to [0, 60]
        if table_scores:
            max_s = max(table_scores.values())
            if max_s > 0:
                table_scores = {t: min(60.0, s / max_s * 60) for t, s in table_scores.items()}
        return table_scores

    # ── History index (question → table) ─────────────────────────────────────

    def add_question(self, question: str, table: str) -> None:
        """
        Record that `question` was successfully answered by querying `table`.
        Call this after every successful SQL execution.
        Persists to history_index.json incrementally.
        """
        if not question.strip() or not table.strip():
            return
        ts = datetime.utcnow().isoformat()
        posting = (question, table, ts)
        tokens = _tokenise(question)
        with self._lock:
            for tok in tokens:
                lst = self._history.setdefault(tok, [])
                # Avoid exact duplicates (same question + table, ignoring timestamp)
                if not any(q == question and t == table for q, t, _ in lst):
                    lst.append(posting)
                    # Cap list size — drop oldest entries
                    if len(lst) > MAX_HISTORY_PER_TOKEN:
                        self._history[tok] = lst[-MAX_HISTORY_PER_TOKEN:]
        self._save_history_to_disk()
        logger.debug(f"[Index] History: recorded '{question[:60]}' → {table}")

    def score_tables_by_history(self, question: str) -> Dict[str, float]:
        """
        Return {table: score} boost based on past questions that match the current one.

        Scoring:
          - For each question token that hits a history posting, accumulate +1 per hit.
          - Normalise to [0, 40] so history boosts but doesn't dominate schema scoring.
        """
        if not self._history:
            return {}

        tokens = _tokenise(question)
        table_scores: Dict[str, float] = {}

        with self._lock:
            for tok in tokens:
                for q, tbl, _ in self._history.get(tok, []):
                    table_scores[tbl] = table_scores.get(tbl, 0.0) + 1.0

        if table_scores:
            max_s = max(table_scores.values())
            if max_s > 0:
                table_scores = {t: min(40.0, s / max_s * 40) for t, s in table_scores.items()}
        return table_scores

    # ── Value search (for hallucination guard) ────────────────────────────────

    def search_value(self, candidate: str, table: Optional[str] = None) -> SearchResult:
        """
        Look up a candidate value using the inverted index + optional embedding reranker.

        Stage 1 — Exact hash lookup  (O(1))
        Stage 2 — Token intersection  (inverted index posting list lookup)
        Stage 3 — Token overlap score
        Stage 4 — Embedding cosine similarity on top-k candidates
        Stage 5 — Confidence threshold gating
        """
        if not self._ready or not candidate.strip():
            return SearchResult(query=candidate, found=False, exact=False, confidence=0.0)

        cand = candidate.strip().lower()

        # ── Stage 1: Exact hash ───────────────────────────────────────────────
        h = _val_hash(cand)
        with self._lock:
            exact_hit = self._exact.get(h)

        if exact_hit:
            tbl, col, val = exact_hit
            if table is None or tbl == table:
                return SearchResult(
                    query=cand, found=True, exact=True, confidence=1.0,
                    top_matches=[{"table": tbl, "col": col, "value": val,
                                  "token_score": 1.0, "emb_score": 1.0, "confidence": 1.0}],
                )

        # ── Stage 2: Token intersection ───────────────────────────────────────
        tokens = _tokenise(cand)
        if not tokens:
            return SearchResult(query=cand, found=False, exact=False, confidence=0.0)

        # candidate_counts[(table, col, value)] = number of tokens that matched
        candidate_counts: Dict[Tuple[str, str, str], int] = {}

        with self._lock:
            for tok in tokens:
                for posting in self._values.get(tok, []):
                    tbl, col, val = posting
                    if table and tbl != table:
                        continue
                    candidate_counts[posting] = candidate_counts.get(posting, 0) + 1

        if not candidate_counts:
            return SearchResult(query=cand, found=False, exact=False, confidence=0.0)

        # ── Stage 3: Token overlap score ──────────────────────────────────────
        n_tokens = len(tokens)
        scored: List[Dict] = []

        for (tbl, col, val), hit_count in candidate_counts.items():
            # Symmetric overlap: min(matched_in_query, matched_in_value) / max(len_q, len_v)
            val_tokens = _tokenise(val)
            overlap = hit_count / max(n_tokens, len(val_tokens))
            scored.append({
                "table": tbl, "col": col, "value": val,
                "token_score": round(overlap, 3),
                "emb_score": 0.0,
                "confidence": 0.0,
            })

        scored.sort(key=lambda x: x["token_score"], reverse=True)
        top_k = scored[:EMB_TOP_K]

        # ── Stage 4: Embedding reranking ──────────────────────────────────────
        try:
            model     = self._load_embed_model()
            cand_emb  = model.encode([cand], normalize_embeddings=True)[0]
            val_texts = [m["value"] for m in top_k]
            val_embs  = model.encode(val_texts, normalize_embeddings=True,
                                     show_progress_bar=False, batch_size=32)
            sims = np.dot(val_embs, cand_emb)

            for i, m in enumerate(top_k):
                m["emb_score"] = round(float(sims[i]), 3)
                # Stage 5: Combined confidence
                m["confidence"] = round(0.35 * m["token_score"] + 0.65 * max(float(sims[i]), 0.0), 3)
        except Exception:
            # Embedding unavailable — fall back to token score only
            for m in top_k:
                m["confidence"] = m["token_score"]

        top_k.sort(key=lambda x: x["confidence"], reverse=True)
        best = top_k[0]["confidence"] if top_k else 0.0

        return SearchResult(
            query=cand,
            found=best >= FOUND_THRESHOLD,
            exact=False,
            confidence=best,
            top_matches=top_k[:5],
        )

    # ── Utilities ─────────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        return self._ready

    def _load_embed_model(self):
        if self._embed_model is None:
            from sentence_transformers import SentenceTransformer
            self._embed_model = SentenceTransformer(self._embed_model_name)
        return self._embed_model

    def stats(self) -> Dict:
        with self._lock:
            history_entries = sum(len(v) for v in self._history.values())
            return {
                "ready":           self._ready,
                "schema_tokens":   len(self._schema),
                "value_tokens":    len(self._values),
                "exact_hashes":    len(self._exact),
                "history_tokens":  len(self._history),
                "history_entries": history_entries,
                "index_dir":       str(self._dir),
            }


# ── Module-level singleton ─────────────────────────────────────────────────────

_instance: Optional[InvertedIndex] = None


def init_inverted_index(
    data_service,
    index_dir: str = "",
    embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    background: bool = True,
) -> InvertedIndex:
    global _instance
    _instance = InvertedIndex(index_dir=index_dir, embed_model_name=embed_model_name)
    _instance.load_or_build(data_service, background=background)
    return _instance


def get_inverted_index() -> Optional[InvertedIndex]:
    return _instance
