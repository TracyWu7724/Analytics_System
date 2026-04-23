"""
indexer.py — FAISS index construction, persistence, and end-to-end pipeline.

Responsibilities:
  - Build a FAISS IndexFlatIP (cosine similarity on L2-normalised vectors)
  - Save / load the FAISS index
  - Orchestrate the full PDF → corpus → embeddings → index pipeline
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

import faiss
import numpy as np
from tqdm import tqdm

try:
    from .parser import PdfParser
    from .chunker import Chunker
    from .embedded import Embedder
    from ..rag_config import IndexingConfig
    from ..rag_modeling import CorpusChunk, IndexArtifacts
except ImportError:
    from parser import PdfParser
    from chunker import Chunker
    from embedded import Embedder
    from rag_config import IndexingConfig
    from rag_modeling import CorpusChunk, IndexArtifacts


class FaissIndexer:
    """
    Builds and persists a FAISS inner-product index from pre-computed embeddings.
    """

    def __init__(self) -> None:
        self.index: Optional[faiss.Index] = None

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def build(self, embeddings: np.ndarray) -> faiss.Index:
        """
        Create an IndexFlatIP from *embeddings*.

        Vectors must already be L2-normalised (inner product == cosine similarity).

        Args:
            embeddings: float32 array of shape (n_docs, dim).

        Returns:
            The populated faiss.Index object.
        """
        dim = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dim)
        self.index.add(embeddings.astype(np.float32))
        print(f"FAISS index built: {self.index.ntotal} vectors, dim={dim}")
        return self.index

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, output_dir: str, model_name: str) -> str:
        """
        Write the FAISS index to *output_dir*.

        File name pattern: embeddings_<safe_model_name>.index

        Args:
            output_dir:  Directory to write into (created if absent).
            model_name:  Embedding model name, used to derive the filename.

        Returns:
            Full path to the written index file.

        Raises:
            ValueError: If build() has not been called yet.
        """
        if self.index is None:
            raise ValueError("No index to save. Call build() first.")

        os.makedirs(output_dir, exist_ok=True)
        safe_name = model_name.replace("/", "_").replace(".", "-")
        index_path = os.path.join(output_dir, f"embeddings_{safe_name}.index")
        faiss.write_index(self.index, index_path)
        print(f"Saved FAISS index → {index_path}")
        return index_path

    def load(self, index_path: str) -> faiss.Index:
        """
        Load a FAISS index from disk.

        Args:
            index_path: Path to the .index file.

        Returns:
            Loaded faiss.Index object.
        """
        self.index = faiss.read_index(index_path)
        print(f"Loaded FAISS index from {index_path}  ({self.index.ntotal} vectors)")
        return self.index


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------

class IndexingPipeline:
    """
    Orchestrates the full pipeline:

        PDF files  →  corpus JSONL  →  embeddings  →  FAISS index

    Usage::

        pipeline = IndexingPipeline(
            input_dir="./data/pdfs",
            output_dir="./embeddings",
            corpus_path="./corpus.jsonl",
            embed_model_name="intfloat/e5-base-v2",
        )
        pipeline.run()
    """

    def __init__(
        self,
        input_dir: str,
        output_dir: str,
        corpus_path: str,
        embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> None:
        """
        Args:
            input_dir:        Directory containing source PDF files.
            output_dir:       Directory to write embeddings / index files.
            corpus_path:      Path to write (or read) the intermediate corpus JSONL.
            embed_model_name: SentenceTransformer model for encoding.
        """
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.corpus_path = corpus_path

        self.parser = PdfParser()
        self.chunker = Chunker()
        self.embedder = Embedder(embed_model_name)
        self.indexer = FaissIndexer()

    @classmethod
    def from_config(cls, config: IndexingConfig) -> "IndexingPipeline":
        pipeline = cls(
            input_dir=str(config.input_dir),
            output_dir=str(config.output_dir),
            corpus_path=str(config.corpus_path),
            embed_model_name=config.embed_model_name,
        )
        pipeline.parser = PdfParser(
            strategy=config.parser_strategy,
            infer_table_structure=config.infer_table_structure,
        )
        pipeline.chunker = Chunker(
            combine_under_n_chars=config.combine_under_n_chars,
            max_characters=config.max_characters,
        )
        return pipeline

    # ------------------------------------------------------------------
    # Steps (can be called individually)
    # ------------------------------------------------------------------

    def build_corpus(self) -> List[Dict]:
        """
        Parse all PDFs in *input_dir* and write a corpus JSONL.

        Returns:
            List of corpus entry dicts.
        """
        pdf_files = self.parser.pdf_files(self.input_dir)
        corpus: List[Dict] = []

        for filename in tqdm(pdf_files, desc="Processing PDFs"):
            path = os.path.join(self.input_dir, filename)
            product_id = self.parser.extract_product_id(filename)
            product_uuid = self.parser.product_uuid(product_id)

            try:
                elements = self.parser.parse(path)
                chunks = self.chunker.chunk(elements)
                for idx, text in enumerate(chunks):
                    corpus.append(
                        CorpusChunk(
                            id=f"{product_uuid}::{idx}",
                            text=text,
                            product_id=product_id,
                            product_uuid=product_uuid,
                            source_file=filename,
                            chunk_index=idx,
                        ).to_dict()
                    )
            except Exception as exc:
                print(f"[WARN] Skipping {filename}: {exc}")

        if not corpus:
            raise ValueError(f"No corpus chunks were produced from {self.input_dir}")

        os.makedirs(os.path.dirname(os.path.abspath(self.corpus_path)), exist_ok=True)
        with open(self.corpus_path, "w", encoding="utf-8") as fh:
            for entry in corpus:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

        print(f"Corpus saved: {len(corpus)} chunks → {self.corpus_path}")
        return corpus

    def embed_corpus(self, corpus: Optional[List[Dict]] = None) -> np.ndarray:
        """
        Encode corpus chunks and save embeddings + metadata to *output_dir*.

        Args:
            corpus: Pre-built corpus list. If None, loads from *corpus_path*.

        Returns:
            Embeddings array of shape (n_chunks, dim).
        """
        if corpus is None:
            corpus = Embedder.load_corpus(self.corpus_path)

        embeddings = self.embedder.encode_corpus_entries(corpus)
        self.embedder.save(self.output_dir, metadata=corpus)
        return embeddings

    def build_index(self, embeddings: Optional[np.ndarray] = None) -> str:
        """
        Build and save a FAISS index from *embeddings*.

        Args:
            embeddings: Pre-computed array. If None, uses self.embedder.embeddings.

        Returns:
            Path to the saved .index file.
        """
        if embeddings is None:
            if self.embedder.embeddings is None:
                raise ValueError("No embeddings available. Call embed_corpus() first.")
            embeddings = self.embedder.embeddings

        self.indexer.build(embeddings)
        return self.indexer.save(self.output_dir, self.embedder.model_name)

    def save_manifest(self, artifacts: IndexArtifacts) -> str:
        """Persist a small JSON manifest describing the built artifacts."""
        manifest_path = os.path.join(self.output_dir, "index_manifest.json")
        os.makedirs(self.output_dir, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(artifacts.to_dict(), fh, ensure_ascii=False, indent=2)
        return manifest_path

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def run(self) -> IndexArtifacts:
        """
        Execute all three steps in sequence:
          1. build_corpus   — PDF → corpus JSONL
          2. embed_corpus   — corpus → embeddings + metadata
          3. build_index    — embeddings → FAISS index
        """
        corpus = self.build_corpus()
        embeddings = self.embed_corpus(corpus)
        index_path = self.build_index(embeddings)
        safe_name = self.embedder.model_name.replace("/", "_").replace(".", "-")
        artifacts = IndexArtifacts(
            corpus_path=self.corpus_path,
            embeddings_path=os.path.join(self.output_dir, f"embeddings_{safe_name}.npy"),
            metadata_path=os.path.join(self.output_dir, f"embeddings_{safe_name}_meta.jsonl"),
            index_path=index_path,
            total_chunks=len(corpus),
            embedding_model=self.embedder.model_name,
        )
        manifest_path = self.save_manifest(artifacts)
        print(f"\nIndexing complete. Index written to: {index_path}")
        print(f"Manifest written to: {manifest_path}")
        return artifacts


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pipeline = IndexingPipeline.from_config(IndexingConfig(embed_model_name="intfloat/e5-base-v2"))
    pipeline.run()
