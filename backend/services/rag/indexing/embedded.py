"""
embedded.py — Text embedding with sentence-transformers.

Responsibilities:
  - Load a SentenceTransformer model
  - Encode a list of text chunks into a normalised float32 numpy array
  - Save / load embeddings and metadata to / from disk
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer


class Embedder:
    """
    Encodes text chunks into dense vectors using a SentenceTransformer model.
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Args:
            model_name: HuggingFace model ID or local path for SentenceTransformer.
        """
        self.model_name = model_name
        print(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.embeddings: Optional[np.ndarray] = None

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def encode(self, texts: List[str], show_progress: bool = True) -> np.ndarray:
        """
        Encode *texts* into L2-normalised float32 embeddings.

        Args:
            texts: List of text strings to embed.
            show_progress: Show a tqdm progress bar during encoding.

        Returns:
            numpy array of shape (len(texts), embedding_dim), dtype float32.
        """
        if not texts:
            raise ValueError("Cannot encode an empty corpus.")

        print(f"Encoding {len(texts)} chunks with '{self.model_name}'…")
        self.embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
        ).astype(np.float32)
        print(f"Embeddings shape: {self.embeddings.shape}")
        return self.embeddings

    def encode_corpus_entries(self, corpus: List[Dict], show_progress: bool = True) -> np.ndarray:
        """Encode corpus entries that contain a 'text' field."""
        return self.encode([entry["text"] for entry in corpus], show_progress=show_progress)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, output_dir: str, metadata: Optional[List[Dict]] = None) -> Dict[str, str]:
        """
        Save embeddings (and optionally metadata) to *output_dir*.

        File naming follows the pattern:
            embeddings_<safe_model_name>.npy
            embeddings_<safe_model_name>_meta.jsonl  (if metadata provided)

        Args:
            output_dir: Directory to write files into (created if absent).
            metadata:   List of dicts to serialise alongside embeddings.

        Returns:
            Dict with keys 'embeddings_path' and optionally 'metadata_path'.

        Raises:
            ValueError: If encode() has not been called yet.
        """
        if self.embeddings is None:
            raise ValueError("No embeddings to save. Call encode() first.")

        os.makedirs(output_dir, exist_ok=True)
        safe_name = self._safe_model_name()
        paths: Dict[str, str] = {}

        emb_path = os.path.join(output_dir, f"embeddings_{safe_name}.npy")
        np.save(emb_path, self.embeddings)
        paths["embeddings_path"] = emb_path
        print(f"Saved embeddings → {emb_path}")

        if metadata is not None:
            meta_path = os.path.join(output_dir, f"embeddings_{safe_name}_meta.jsonl")
            with open(meta_path, "w", encoding="utf-8") as fh:
                for entry in metadata:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            paths["metadata_path"] = meta_path
            print(f"Saved metadata   → {meta_path}")

        return paths

    def load(self, embeddings_path: str, metadata_path: Optional[str] = None) -> List[Dict]:
        """
        Load pre-computed embeddings (and optionally metadata) from disk.

        Args:
            embeddings_path: Path to the .npy embeddings file.
            metadata_path:   Optional path to the _meta.jsonl file.

        Returns:
            Loaded metadata list (empty list if *metadata_path* is None).
        """
        self.embeddings = np.load(embeddings_path).astype(np.float32)
        print(f"Loaded embeddings from {embeddings_path}  shape={self.embeddings.shape}")

        metadata: List[Dict] = []
        if metadata_path:
            with open(metadata_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    metadata.append(json.loads(line))
            print(f"Loaded {len(metadata)} metadata entries from {metadata_path}")

        return metadata

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _safe_model_name(self) -> str:
        return self.model_name.replace("/", "_").replace(".", "-")

    @staticmethod
    def load_corpus(corpus_path: str) -> List[Dict]:
        """
        Read a corpus JSONL file into a list of dicts.

        Args:
            corpus_path: Path to the .jsonl corpus file.

        Returns:
            List of entry dicts, each with at least a 'text' key.
        """
        entries: List[Dict] = []
        with open(corpus_path, "r", encoding="utf-8") as fh:
            for line in fh:
                entries.append(json.loads(line))
        print(f"Loaded {len(entries)} entries from {corpus_path}")
        return entries
