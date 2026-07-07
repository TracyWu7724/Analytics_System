"""
indexing/incremental.py — Append a single PDF to an existing FAISS index.

Instead of rebuilding the full index, this loads the existing index + metadata,
embeds only the new document's chunks, and merges them in-place.

Usage
-----
    indexer = IncrementalIndexer(
        embed_dir="/data/embedding",
        embed_model_name="BAAI/bge-base-en-v1.5",
    )
    result = indexer.add_pdf("/tmp/upload.pdf", original_filename="LOCTITE-401.pdf")
"""

from __future__ import annotations

import json
import os
from typing import Optional

import faiss
import numpy as np

try:
    from .parser import PdfParser
    from .chunker import Chunker
    from .embedded import Embedder
    from ..rag_modeling import CorpusChunk
except ImportError:
    from parser import PdfParser
    from chunker import Chunker
    from embedded import Embedder
    from rag_modeling import CorpusChunk


def _model_to_key(model_name: str) -> str:
    return model_name.replace("/", "_").replace(".", "-")


class IncrementalIndexer:
    """
    Appends one PDF's chunks to an existing FAISS index + metadata file.
    Creates a fresh index when none exists yet.
    """

    def __init__(
        self,
        embed_dir: str,
        embed_model_name: str = "BAAI/bge-base-en-v1.5",
        parser_strategy: str = "fast",
        kg=None,
        kg_path: str = "",
    ):
        self.embed_dir = embed_dir
        self.embed_model_name = embed_model_name
        self.parser_strategy = parser_strategy
        self.kg = kg
        self.kg_path = kg_path
        self._key = _model_to_key(embed_model_name)

        # Paths that match the naming convention used by _resolve_rag_paths in agent.py
        self.meta_path  = os.path.join(embed_dir, f"embeddings_{self._key}_meta_2.jsonl")
        self.index_path = os.path.join(embed_dir, f"embeddings_{self._key}_2.index")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_pdf(
        self,
        tmp_path: str,
        original_filename: str,
    ) -> dict:
        """
        Parse *tmp_path* as PDF, embed its chunks, and merge into the index.

        Returns
        -------
        {
            "success": bool,
            "filename": str,
            "chunks_added": int,
            "total_vectors": int,
            "error": str | None,
        }
        """
        try:
            # 1. Parse → chunk
            parser  = PdfParser(strategy=self.parser_strategy, infer_table_structure=False)
            chunker = Chunker()

            elements = parser.parse(tmp_path)
            texts    = chunker.chunk(elements)
            if not texts:
                return {"success": False, "error": "No text could be extracted from the PDF."}

            product_id   = parser.extract_product_id(original_filename)
            product_uuid = parser.product_uuid(product_id)

            new_entries = [
                CorpusChunk(
                    id=f"{product_uuid}::{i}",
                    text=text,
                    product_id=product_id,
                    product_uuid=product_uuid,
                    source_file=original_filename,
                    chunk_index=i,
                ).to_dict()
                for i, text in enumerate(texts)
            ]

            # 2. Embed
            embedder   = Embedder(self.embed_model_name)
            new_vecs   = embedder.encode([e["text"] for e in new_entries], show_progress=False)

            # 3. Load or create FAISS index
            os.makedirs(self.embed_dir, exist_ok=True)
            if os.path.exists(self.index_path):
                index = faiss.read_index(self.index_path)
            else:
                dim   = new_vecs.shape[1]
                index = faiss.IndexFlatIP(dim)

            # 4. Add new vectors
            index.add(new_vecs.astype(np.float32))

            # 5. Save updated index
            faiss.write_index(index, self.index_path)

            # 6. Append metadata (skip duplicates by source_file + chunk_index)
            existing_ids: set[str] = set()
            if os.path.exists(self.meta_path):
                with open(self.meta_path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        entry = json.loads(line)
                        existing_ids.add(entry.get("id", ""))

            with open(self.meta_path, "a", encoding="utf-8") as fh:
                written = 0
                for entry in new_entries:
                    if entry["id"] not in existing_ids:
                        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        written += 1

            # 7. Trigger async KG build for newly added chunks
            if self.kg is not None and self.kg_path and written > 0:
                try:
                    from ..kg.kg_builder import KGBuilder
                    builder = KGBuilder(self.kg, self.kg_path)
                    builder.build_async(new_entries[:written])
                except Exception:
                    pass  # KG build failure must never fail the upload

            return {
                "success": True,
                "filename": original_filename,
                "chunks_added": written,
                "total_vectors": int(index.ntotal),
                "error": None,
            }

        except Exception as exc:
            return {"success": False, "filename": original_filename, "error": str(exc)}
