"""Indexing utilities for the RAG service."""


def __getattr__(name):
    if name in ("FaissIndexer", "IndexingPipeline"):
        from .indexer import FaissIndexer, IndexingPipeline
        return {"FaissIndexer": FaissIndexer, "IndexingPipeline": IndexingPipeline}[name]
    if name == "PdfParser":
        from .parser import PdfParser
        return PdfParser
    if name == "Chunker":
        from .chunker import Chunker
        return Chunker
    if name == "Embedder":
        from .embedded import Embedder
        return Embedder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Chunker", "Embedder", "FaissIndexer", "IndexingPipeline", "PdfParser"]
