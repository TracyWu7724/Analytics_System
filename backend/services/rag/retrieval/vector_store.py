"""FAISS-backed vector store for RAG retrieval."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

try:
    from ..rag_modeling import RetrievalResult
except ImportError:
    from rag_modeling import RetrievalResult


class FaissVectorStore:
    """Load embeddings metadata and provide global/per-product FAISS search."""

    def __init__(
        self,
        metadata_path: str,
        faiss_path: str,
        embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        trust_remote_code: bool = False,
    ):
        self.metadata_path = Path(metadata_path)
        self.faiss_path = Path(faiss_path)
        self.embed_model_name = embed_model_name
        self.embed_model = SentenceTransformer(embed_model_name, trust_remote_code=trust_remote_code)

        self.texts, self.metadata = self._load_metadata(self.metadata_path)
        self.index = faiss.read_index(str(self.faiss_path))
        self.product_chunk_faiss: dict[str, faiss.Index] = {}
        self.product_chunk_refs: dict[str, list[tuple[str, dict]]] = {}
        self.product_ids: dict[str, str] = {}
        self._build_product_indices()

    @staticmethod
    def _load_metadata(metadata_path: Path) -> tuple[list[str], list[dict]]:
        texts: list[str] = []
        metadata: list[dict] = []
        with metadata_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                entry = json.loads(line)
                texts.append(entry["text"])
                metadata.append(entry)
        return texts, metadata

    def _build_product_indices(self):
        grouped_indices: dict[str, list[int]] = defaultdict(list)
        grouped_records: dict[str, list[tuple[str, dict]]] = defaultdict(list)

        for idx, meta in enumerate(self.metadata):
            product_uuid = meta.get("product_uuid")
            if not product_uuid:
                continue
            grouped_indices[product_uuid].append(idx)
            grouped_records[product_uuid].append((self.texts[idx], meta))
            self.product_ids[product_uuid] = meta.get("product_id", product_uuid)

        for product_uuid, positions in grouped_indices.items():
            embeddings = np.array([self.index.reconstruct(int(i)) for i in positions], dtype="float32")
            product_index = faiss.IndexFlatIP(embeddings.shape[1])
            product_index.add(embeddings)
            self.product_chunk_faiss[product_uuid] = product_index
            self.product_chunk_refs[product_uuid] = grouped_records[product_uuid]

    def encode_query(self, query: str) -> np.ndarray:
        return self.embed_model.encode([query], normalize_embeddings=True, convert_to_numpy=True).astype("float32")

    def search(self, query: str, k: int = 5) -> list[RetrievalResult]:
        k = min(k, len(self.texts))
        if k <= 0:
            return []

        distances, indices = self.index.search(self.encode_query(query), k)
        results: list[RetrievalResult] = []
        for score, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self.metadata):
                continue
            results.append(
                RetrievalResult(
                    text=self.texts[idx],
                    score=float(score),
                    metadata=self.metadata[idx],
                    source="vector",
                )
            )
        return results

    def search_within_product(self, product_uuid: str, query: str, k: int = 5) -> list[RetrievalResult]:
        if product_uuid not in self.product_chunk_faiss:
            return []

        product_index = self.product_chunk_faiss[product_uuid]
        refs = self.product_chunk_refs[product_uuid]
        k = min(k, len(refs))
        if k <= 0:
            return []

        distances, indices = product_index.search(self.encode_query(query), k)
        results: list[RetrievalResult] = []
        for score, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(refs):
                continue
            text, meta = refs[idx]
            results.append(
                RetrievalResult(
                    text=text,
                    score=float(score),
                    metadata=meta,
                    source="vector_product",
                )
            )
        return results

    def identify_relevant_products(self, query: str, top_n: int = 3) -> list[tuple[str, str, float]]:
        top_hits = self.search(query, k=min(20, len(self.texts)))
        product_scores: dict[str, list[float]] = defaultdict(list)

        for hit in top_hits:
            product_uuid = hit.metadata.get("product_uuid")
            if product_uuid:
                product_scores[product_uuid].append(hit.score)

        ranked = [
            (product_uuid, self.product_ids.get(product_uuid, product_uuid), max(scores))
            for product_uuid, scores in product_scores.items()
        ]
        ranked.sort(key=lambda item: item[2], reverse=True)
        return ranked[:top_n]
