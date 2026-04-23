"""Configuration objects for the RAG indexing and pre-retrieval pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


RAG_ROOT = Path(__file__).resolve().parent


@dataclass(slots=True)
class IndexingConfig:
    input_dir: Path = field(default_factory=lambda: RAG_ROOT / "data")
    output_dir: Path = field(default_factory=lambda: RAG_ROOT / "artifacts")
    corpus_path: Path = field(default_factory=lambda: RAG_ROOT / "artifacts" / "corpus.jsonl")
    embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    parser_strategy: str = "hi_res"
    infer_table_structure: bool = True
    combine_under_n_chars: int = 700
    max_characters: int = 1000


@dataclass(slots=True)
class QueryPreparationConfig:
    lowercase: bool = True
    collapse_whitespace: bool = True
    remove_punctuation: bool = False
    max_expansions: int = 6
    keep_original: bool = True
