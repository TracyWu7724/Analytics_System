"""
knowledge_graph.py — In-memory knowledge graph backed by NetworkX DiGraph.

Supports:
  - Adding entities (nodes) and relations (edges)
  - Multi-hop entity expansion for query enrichment
  - JSON serialization / deserialization
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class KnowledgeGraph:
    """Thin wrapper around a NetworkX directed graph."""

    def __init__(self):
        try:
            import networkx as nx
            self._g = nx.DiGraph()
        except ImportError:
            logger.warning("[KG] networkx not installed — KG disabled")
            self._g = None

    # ── Mutation ──────────────────────────────────────────────────────────────

    def add_entity(self, name: str, label: str = "", source: str = "", **attrs) -> None:
        if self._g is None:
            return
        key = name.lower()
        if self._g.has_node(key):
            self._g.nodes[key]["mentions"] = self._g.nodes[key].get("mentions", 1) + 1
        else:
            self._g.add_node(key, name=name, label=label, source=source, mentions=1, **attrs)

    def add_relation(self, subject: str, predicate: str, obj: str, source: str = "", confidence: float = 1.0) -> None:
        if self._g is None:
            return
        s_key = subject.lower()
        o_key = obj.lower()
        if not self._g.has_node(s_key):
            self._g.add_node(s_key, name=subject, label="", source=source, mentions=1)
        if not self._g.has_node(o_key):
            self._g.add_node(o_key, name=obj, label="", source=source, mentions=1)
        self._g.add_edge(s_key, o_key, predicate=predicate, source=source, confidence=confidence)

    # ── Query ─────────────────────────────────────────────────────────────────

    def expand_entity(self, name: str, hops: int = 2) -> list[str]:
        """Return the `name` of all nodes reachable within `hops` from `name`."""
        if self._g is None:
            return []
        key = name.lower()
        if not self._g.has_node(key):
            # Try prefix match
            for n in self._g.nodes:
                if n.startswith(key) or key.startswith(n):
                    key = n
                    break
            else:
                return []

        try:
            import networkx as nx
            subgraph_nodes = nx.ego_graph(self._g, key, radius=hops, undirected=True).nodes
            results = []
            for n in subgraph_nodes:
                if n != key:
                    results.append(self._g.nodes[n].get("name", n))
            return results
        except Exception:
            return []

    def neighbors_with_predicates(self, name: str) -> list[dict]:
        """Return all direct neighbors with their predicate labels."""
        if self._g is None:
            return []
        key = name.lower()
        if not self._g.has_node(key):
            return []
        result = []
        for _, nbr, data in self._g.out_edges(key, data=True):
            result.append({
                "neighbor": self._g.nodes[nbr].get("name", nbr),
                "predicate": data.get("predicate", "related_to"),
            })
        return result

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str) -> None:
        if self._g is None:
            return
        try:
            import networkx as nx
            data = nx.node_link_data(self._g)
            Path(path).write_text(json.dumps(data, ensure_ascii=False))
            logger.info(f"[KG] Saved {self._g.number_of_nodes()} nodes, {self._g.number_of_edges()} edges → {path}")
        except Exception as exc:
            logger.error(f"[KG] Save failed: {exc}")

    def load(self, path: str) -> bool:
        if self._g is None:
            return False
        try:
            import networkx as nx
            raw = json.loads(Path(path).read_text())
            self._g = nx.node_link_graph(raw, directed=True)
            logger.info(f"[KG] Loaded {self._g.number_of_nodes()} nodes, {self._g.number_of_edges()} edges from {path}")
            return True
        except Exception as exc:
            logger.warning(f"[KG] Load failed: {exc}")
            return False

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        if self._g is None:
            return {"enabled": False, "reason": "networkx not installed"}
        return {
            "enabled": True,
            "nodes": self._g.number_of_nodes(),
            "edges": self._g.number_of_edges(),
        }
