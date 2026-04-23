"""Shared dataclasses for the RAG pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CorpusChunk:
    id: str
    text: str
    product_id: str
    product_uuid: str
    source_file: str
    chunk_index: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class IndexArtifacts:
    corpus_path: str
    embeddings_path: str
    index_path: str
    metadata_path: str | None = None
    total_chunks: int = 0
    embedding_model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PreparedQuery:
    original: str
    rewritten: str
    expansions: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)

    def all_queries(self) -> list[str]:
        ordered = [self.original, self.rewritten, *self.expansions]
        seen: set[str] = set()
        result: list[str] = []
        for item in ordered:
            normalized = item.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result


@dataclass(slots=True)
class RetrievalResult:
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "vector"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
