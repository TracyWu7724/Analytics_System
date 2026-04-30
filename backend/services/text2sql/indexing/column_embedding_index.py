"""
column_embedding_index.py — Semantic vector index over column names.

Each column is embedded as:
    "{col_name} in {table_simple_name}"  (e.g. "Revenue in loctite_sales_data")

At query time the question is embedded and cosine-similarity is computed against
all column vectors. The top-k matches are aggregated per table to produce a
{table_full_name: score} boost dict, compatible with the existing schema_boost
and history_boost in table_matching.get_relevant_tables().

Persistence: backend/index/column_embeddings.faiss + column_embeddings_meta.json
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_INDEX_DIR = Path(__file__).resolve().parents[3] / "index"
_DEFAULT_MODEL     = os.getenv("RAG_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# How many top column matches to aggregate per query
_TOP_K = 20
# Score ceiling blended with schema/history boosts in table_matching
_MAX_SCORE = 60.0


class ColumnEmbeddingIndex:
    """
    Builds and queries a FAISS flat-cosine index over column descriptors.

    Thread-safe; build runs in a background thread so startup is non-blocking.
    """

    def __init__(
        self,
        index_dir: str | Path = _DEFAULT_INDEX_DIR,
        embed_model_name: str = _DEFAULT_MODEL,
    ):
        self._dir   = Path(index_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._faiss_path = self._dir / "column_embeddings.faiss"
        self._meta_path  = self._dir / "column_embeddings_meta.json"

        self._embed_model_name = embed_model_name
        self._model   = None          # lazy-loaded
        self._index   = None          # faiss.IndexFlatIP
        self._meta: List[Dict] = []   # [{text, table, col}, ...]
        self._lock    = threading.RLock()
        self._ready   = False

        self._try_load()

    # ── Public API ────────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        return self._ready

    def build(self, data_service, background: bool = True) -> None:
        """Rebuild the index from Databricks schema. Safe to call at startup."""
        if background:
            t = threading.Thread(target=self._build_sync, args=(data_service,), daemon=True)
            t.start()
        else:
            self._build_sync(data_service)

    def score_tables(self, question: str, top_k: int = _TOP_K) -> Dict[str, float]:
        """
        Return {table_full_name: score ∈ [0, 60]} based on semantic similarity
        between the question and column descriptors.
        """
        if not self._ready or self._index is None or not self._meta:
            return {}

        try:
            model = self._get_model()
            q_vec = model.encode([question], normalize_embeddings=True).astype("float32")

            with self._lock:
                k = min(top_k, len(self._meta))
                sims, idxs = self._index.search(q_vec, k)

            table_scores: Dict[str, float] = {}
            for sim, idx in zip(sims[0], idxs[0]):
                if idx < 0 or sim <= 0:
                    continue
                entry = self._meta[idx]
                tbl   = entry["table"]
                table_scores[tbl] = table_scores.get(tbl, 0.0) + float(sim)

            # Normalise to [0, _MAX_SCORE]
            if table_scores:
                mx = max(table_scores.values())
                if mx > 0:
                    table_scores = {t: s / mx * _MAX_SCORE for t, s in table_scores.items()}

            return table_scores

        except Exception as exc:
            logger.warning(f"[ColEmb] score_tables failed: {exc}")
            return {}

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_sync(self, data_service) -> None:
        try:
            import faiss

            tables = data_service.get_table_names()
            if not tables:
                logger.warning("[ColEmb] No tables found — skipping build")
                return

            # Collect (text, table, col) for every column
            records: List[Dict] = []
            for table in tables:
                try:
                    schema = data_service.get_table_schema(table)
                except Exception:
                    continue
                simple = table.split(".")[-1]
                for col_info in schema:
                    col = col_info.get("name", "")
                    ctype = col_info.get("type", "")
                    if not col:
                        continue
                    # Embed just the column name — pure semantic signal.
                    # The table it belongs to is stored in metadata, not the text.
                    col_readable = col.replace("_", " ").lower()
                    records.append({"text": col_readable, "table": table, "col": col, "type": ctype})

            if not records:
                logger.warning("[ColEmb] No columns found — skipping build")
                return

            logger.info(f"[ColEmb] Embedding {len(records)} columns…")
            model = self._get_model()
            texts = [r["text"] for r in records]
            vecs  = model.encode(texts, normalize_embeddings=True, show_progress_bar=False).astype("float32")

            dim   = vecs.shape[1]
            index = faiss.IndexFlatIP(dim)   # inner product = cosine (vecs are L2-normalised)
            index.add(vecs)

            with self._lock:
                self._index = index
                self._meta  = records
                self._ready = True

            self._save(index, records)
            logger.info(f"[ColEmb] Built — {len(records)} columns across {len(tables)} tables")

        except Exception as exc:
            logger.error(f"[ColEmb] Build failed: {exc}")

    # ── Persistence ───────────────────────────────────────────────────────────

    def _try_load(self) -> bool:
        try:
            import faiss
            if not self._faiss_path.exists() or not self._meta_path.exists():
                return False
            index = faiss.read_index(str(self._faiss_path))
            with open(self._meta_path) as f:
                meta = json.load(f)
            with self._lock:
                self._index = index
                self._meta  = meta
                self._ready = True
            logger.info(f"[ColEmb] Loaded {len(meta)} column vectors from disk")
            return True
        except Exception as exc:
            logger.warning(f"[ColEmb] Load failed ({exc}) — will rebuild on next build() call")
            return False

    def _save(self, index, meta: List[Dict]) -> None:
        try:
            import faiss
            faiss.write_index(index, str(self._faiss_path))
            with open(self._meta_path, "w") as f:
                json.dump(meta, f)
        except Exception as exc:
            logger.warning(f"[ColEmb] Save failed: {exc}")

    # ── Model ─────────────────────────────────────────────────────────────────

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._embed_model_name)
        return self._model


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[ColumnEmbeddingIndex] = None
_instance_lock = threading.Lock()


def get_column_embedding_index(
    index_dir: str | Path = _DEFAULT_INDEX_DIR,
    embed_model_name: str = _DEFAULT_MODEL,
) -> ColumnEmbeddingIndex:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ColumnEmbeddingIndex(index_dir=index_dir, embed_model_name=embed_model_name)
    return _instance
