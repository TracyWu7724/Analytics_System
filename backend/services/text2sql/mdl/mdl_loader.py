"""
mdl_loader.py — Load and cache the MDL semantic layer from backend/mdl/schema.yaml.

Uses mtime-based caching so the file can be edited without a server restart.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_MDL_PATH = Path(__file__).resolve().parents[4] / "mdl" / "schema.yaml"

_cache_mtime: float = 0.0
_cache_config: Optional["MDLConfig"] = None


@dataclass
class MetricDef:
    name: str
    description: str
    expression: str
    synonyms: list[str] = field(default_factory=list)


@dataclass
class JoinDef:
    left_table: str
    right_table: str
    on: str
    description: str = ""


@dataclass
class MDLConfig:
    version: str
    metrics: list[MetricDef]
    joins: list[JoinDef]
    column_descriptions: dict[str, dict[str, str]]
    value_constraints: dict[str, list[str]]
    synonyms: dict[str, list[str]]

    def metric_by_name(self, name: str) -> Optional[MetricDef]:
        for m in self.metrics:
            if m.name.lower() == name.lower():
                return m
        return None

    def metric_for_synonym(self, word: str) -> Optional[MetricDef]:
        word_l = word.lower()
        for m in self.metrics:
            if word_l == m.name.lower() or word_l in [s.lower() for s in m.synonyms]:
                return m
        return None

    def joins_for_table(self, table: str) -> list[JoinDef]:
        t = table.lower().split(".")[-1]
        return [j for j in self.joins if j.left_table.lower() == t or j.right_table.lower() == t]


def load_mdl(path: Optional[str] = None) -> Optional[MDLConfig]:
    """
    Load the MDL config from disk.  Uses mtime-based cache.
    Returns None if the file doesn't exist or fails to parse.
    """
    global _cache_mtime, _cache_config

    mdl_path = Path(path) if path else _DEFAULT_MDL_PATH
    if not mdl_path.exists():
        return None

    try:
        mtime = mdl_path.stat().st_mtime
        if _cache_config is not None and mtime == _cache_mtime:
            return _cache_config

        import yaml
        raw = yaml.safe_load(mdl_path.read_text())

        metrics = [
            MetricDef(
                name=m["name"],
                description=m.get("description", ""),
                expression=m["expression"],
                synonyms=m.get("synonyms", []),
            )
            for m in raw.get("metrics", [])
        ]
        joins = [
            JoinDef(
                left_table=j["left_table"],
                right_table=j["right_table"],
                on=j["on"],
                description=j.get("description", ""),
            )
            for j in raw.get("joins", [])
        ]
        config = MDLConfig(
            version=str(raw.get("version", "1")),
            metrics=metrics,
            joins=joins,
            column_descriptions=raw.get("column_descriptions", {}),
            value_constraints=raw.get("value_constraints", {}),
            synonyms=raw.get("synonyms", {}),
        )
        _cache_mtime = mtime
        _cache_config = config
        logger.info(f"[MDL] Loaded {len(metrics)} metrics, {len(joins)} joins from {mdl_path}")
        return config

    except Exception as exc:
        logger.warning(f"[MDL] Failed to load schema.yaml: {exc}")
        return None
