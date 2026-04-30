"""
product_index.py — Number-centric product inverted index.

For a product name like "LOCTITE 243 Threadlocker" the following keys
are all indexed and resolve back to the canonical full name:

    "243"                       ← numeric ID alone  (primary key)
    "loctite 243"               ← brand + number
    "243 threadlocker"          ← number + first descriptor word
    "loctite 243 threadlocker"  ← full name (normalised)

Design goals
------------
- Users search by product number ("243"), brand+number ("LOCTITE 243"),
  or number+descriptor ("243 Threadlocker").  The numeric part is the
  most specific and reliable fragment — it is always a key.
- Multiple tables are indexed together (sales_data, project_budget,
  inventory_tracker) so a single lookup resolves the canonical name
  regardless of which table the product lives in.
- Thread-safe; background build never blocks the request path.
- Persisted to JSON on disk; reloaded on startup in milliseconds.
- Incremental: individual records can be added / removed without a
  full rebuild.

Lookup pipeline
---------------
1. Number extraction from query (regex)
2. Primary lookup in number index  (O(1) per number)
3. Disambiguation by brand / descriptor token overlap
4. Fallback: full-phrase fuzzy scan when no number is present
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Columns likely to contain product names; checked case-insensitively.
_PRODUCT_COL_HINTS = {
    "product_name", "product", "item_name", "item", "sku", "part_name",
    "part_number", "part", "material", "description", "product_description",
    "product_id",
}

# Tables to always index (fully-qualified names; checked as suffix match).
DEFAULT_PRODUCT_TABLES = {
    "loctite_sales_data",
    "project_budget",
    "inventory_tracker",
}

_INDEX_FILE    = "product_index.json"
_META_FILE     = "product_index_meta.json"
MAX_AGE_HOURS  = 24

# ── Product record ─────────────────────────────────────────────────────────────

@dataclass
class ProductRecord:
    """A single indexed product with its decomposed parts and all variant keys."""
    table:      str
    col:        str
    full_name:  str          # original casing, e.g. "LOCTITE 243 Threadlocker"
    brand:      str          # e.g. "loctite"
    number:     str          # e.g. "243"  (first numeric token; "" if none)
    descriptor: str          # e.g. "threadlocker"
    variants:   List[str] = field(default_factory=list)
    # variants are lowercased keys that all resolve to this record


# ── Parsing helpers ────────────────────────────────────────────────────────────

# Matches a numeric "product number" token: digits optionally followed by
# letters/dashes (e.g. "243", "401", "620A", "495-2").
_NUM_RE = re.compile(r'\b(\d[\w\-]*)\b')


def _split_product_name(name: str) -> Tuple[str, str, str]:
    """
    Decompose a product name into (brand, number, descriptor).

    Strategy:
      1. Find the first numeric token — that is the product number.
      2. Everything before it (lowercased) is the brand.
      3. Everything after it (lowercased) is the descriptor.

    If no numeric token exists, the whole name is treated as brand and
    number/descriptor are empty strings.

    Examples
    --------
    "LOCTITE 243 Threadlocker"   → ("loctite", "243", "threadlocker")
    "LOCTITE 401 Instant Adhesive" → ("loctite", "401", "instant adhesive")
    "Threadlocker Blue"          → ("threadlocker blue", "", "")
    "3M 9472LE Adhesive"         → ("3m", "9472le", "adhesive")
    """
    name = name.strip()
    m = _NUM_RE.search(name)
    if not m:
        return name.lower(), "", ""

    number = m.group(1).lower()
    brand = name[:m.start()].strip().lower()
    descriptor = name[m.end():].strip().lower()
    return brand, number, descriptor


def _build_variants(brand: str, number: str, descriptor: str, full_name: str) -> List[str]:
    """
    Return all lowercased key variants for a product.

    Always includes:
      - number alone             (if non-empty)
      - brand + number           (if brand non-empty)
      - number + first desc word (if descriptor non-empty)
      - full normalised name

    Optionally includes:
      - brand + number + full descriptor (same as full name if single-word brand)
    """
    if not number:
        # No numeric ID — index full name and its words as fallback
        parts = full_name.lower().split()
        variants = [full_name.lower()]
        if len(parts) >= 2:
            variants += [" ".join(parts[:2]), " ".join(parts[-2:])]
        return list(dict.fromkeys(v for v in variants if v))

    full_lower = full_name.lower()
    desc_first = descriptor.split()[0] if descriptor else ""

    candidates = [
        number,                                         # "243"
        f"{brand} {number}".strip() if brand else "",  # "loctite 243"
        f"{number} {desc_first}".strip() if desc_first else "",  # "243 threadlocker"
        f"{brand} {number} {descriptor}".strip() if brand and descriptor else "",  # "loctite 243 threadlocker"
        full_lower,
    ]
    # Also index number + full descriptor (handles multi-word descriptors)
    if descriptor and descriptor != desc_first:
        candidates.append(f"{number} {descriptor}")

    return list(dict.fromkeys(v for v in candidates if v))


# ── ProductIndex ───────────────────────────────────────────────────────────────

class ProductIndex:
    """
    Number-centric inverted index for product names across multiple tables.

    Thread-safe.  Background build/reload never blocks the request path.
    """

    def __init__(
        self,
        index_dir: str = "",
        product_tables: Optional[set] = None,
    ):
        self._dir = Path(index_dir) if index_dir else Path(__file__).resolve().parents[3] / "index"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path      = self._dir / _INDEX_FILE
        self._meta_path = self._dir / _META_FILE

        self._product_tables = product_tables or DEFAULT_PRODUCT_TABLES
        self._max_age = timedelta(hours=MAX_AGE_HOURS)

        # Primary:   number_key → [ProductRecord, ...]
        # Secondary: phrase     → [ProductRecord, ...]
        self._by_number: Dict[str, List[ProductRecord]] = {}
        self._by_phrase: Dict[str, List[ProductRecord]] = {}
        self._all_records: List[ProductRecord] = []

        self._lock  = threading.RLock()
        self._ready = False

    # ── Startup ────────────────────────────────────────────────────────────────

    def load_or_build(self, data_service, background: bool = True) -> None:
        """Load from disk; rebuild from Databricks if missing or stale."""
        if self._load_from_disk():
            logger.info(f"[ProductIndex] Loaded {len(self._all_records)} products from disk")
            self._ready = True
            if self._is_stale():
                logger.info("[ProductIndex] Stale — refreshing in background")
                self._start_build(data_service)
        else:
            logger.info("[ProductIndex] No disk cache — building from Databricks")
            self._start_build(data_service, background=background)

    def rebuild(self, data_service, background: bool = True) -> None:
        """Force full rebuild (call after data changes in Databricks)."""
        self._start_build(data_service, background=background)

    def _start_build(self, data_service, background: bool = True) -> None:
        if background:
            t = threading.Thread(target=self._build_sync, args=(data_service,), daemon=True)
            t.start()
        else:
            self._build_sync(data_service)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_sync(self, data_service) -> None:
        new_records: List[ProductRecord] = []
        try:
            tables = data_service.get_table_names()
            target = [
                t for t in tables
                if any(suffix in t.lower() for suffix in self._product_tables)
            ]
            logger.info(f"[ProductIndex] Building from {len(target)} product table(s)…")

            for table in target:
                try:
                    schema = data_service.get_table_schema(table)
                except Exception:
                    continue

                for col_info in schema:
                    col_name = col_info.get("name", "")
                    if col_name.lower() not in _PRODUCT_COL_HINTS:
                        continue

                    try:
                        rows = data_service.execute_query(
                            f"SELECT DISTINCT `{col_name}` FROM {table} "
                            f"WHERE `{col_name}` IS NOT NULL",
                            custom_limit=2000,
                        )
                        for row in rows:
                            val = str(row.get(col_name, "")).strip()
                            if not val:
                                continue
                            record = self._make_record(table, col_name, val)
                            if record:
                                new_records.append(record)
                        logger.debug(f"[ProductIndex] {table}.{col_name}: {len(rows)} products")
                    except Exception as exc:
                        logger.debug(f"[ProductIndex] Skipped {table}.{col_name}: {exc}")

            with self._lock:
                self._all_records = new_records
                self._rebuild_indexes()
                self._ready = True

            self._save_to_disk()
            logger.info(f"[ProductIndex] Done — {len(new_records)} products indexed")

        except Exception as exc:
            logger.error(f"[ProductIndex] Build failed: {exc}")

    def _make_record(self, table: str, col: str, full_name: str) -> Optional[ProductRecord]:
        try:
            brand, number, descriptor = _split_product_name(full_name)
            variants = _build_variants(brand, number, descriptor, full_name)
            return ProductRecord(
                table=table,
                col=col,
                full_name=full_name,
                brand=brand,
                number=number,
                descriptor=descriptor,
                variants=variants,
            )
        except Exception:
            return None

    def _rebuild_indexes(self) -> None:
        """Rebuild _by_number and _by_phrase from _all_records (called under lock)."""
        by_number: Dict[str, List[ProductRecord]] = {}
        by_phrase:  Dict[str, List[ProductRecord]] = {}

        for rec in self._all_records:
            if rec.number:
                by_number.setdefault(rec.number, []).append(rec)
            for variant in rec.variants:
                by_phrase.setdefault(variant, []).append(rec)

        self._by_number = by_number
        self._by_phrase  = by_phrase

    # ── Disk I/O ───────────────────────────────────────────────────────────────

    def _save_to_disk(self) -> None:
        try:
            with self._lock:
                data = [asdict(r) for r in self._all_records]
            self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            self._meta_path.write_text(json.dumps({
                "built_at": datetime.utcnow().isoformat(),
                "total":    len(data),
            }, ensure_ascii=False))
            logger.debug(f"[ProductIndex] Saved to {self._path}")
        except Exception as exc:
            logger.error(f"[ProductIndex] Save failed: {exc}")

    def _load_from_disk(self) -> bool:
        try:
            if not self._path.exists():
                return False
            data = json.loads(self._path.read_text())
            records = [ProductRecord(**r) for r in data]
            with self._lock:
                self._all_records = records
                self._rebuild_indexes()
            return True
        except Exception as exc:
            logger.warning(f"[ProductIndex] Load failed: {exc}")
            return False

    def _is_stale(self) -> bool:
        try:
            meta = json.loads(self._meta_path.read_text())
            built_at = datetime.fromisoformat(meta["built_at"])
            return datetime.utcnow() - built_at > self._max_age
        except Exception:
            return True

    # ── Incremental update ─────────────────────────────────────────────────────

    def add_product(self, table: str, col: str, full_name: str) -> None:
        """Add a single product and persist."""
        record = self._make_record(table, col, full_name)
        if not record:
            return
        with self._lock:
            self._all_records.append(record)
            if record.number:
                self._by_number.setdefault(record.number, []).append(record)
            for variant in record.variants:
                self._by_phrase.setdefault(variant, []).append(record)
        self._save_to_disk()

    def remove_product(self, full_name: str) -> None:
        """Remove all records whose full_name matches (case-insensitive) and persist."""
        lower = full_name.strip().lower()
        with self._lock:
            self._all_records = [r for r in self._all_records if r.full_name.lower() != lower]
            self._rebuild_indexes()
        self._save_to_disk()

    # ── Search ─────────────────────────────────────────────────────────────────

    def search(self, query: str, table: Optional[str] = None) -> List[ProductRecord]:
        """
        Find products matching a query fragment.

        Search order:
          1. Exact phrase match (case-insensitive)
          2. Number extracted from query → primary lookup → disambiguate by
             brand / descriptor overlap
          3. Partial phrase scan (query tokens are a subset of a variant)

        Parameters
        ----------
        query : str
            User fragment, e.g. "243", "LOCTITE 243", "243 Threadlocker".
        table : str, optional
            Restrict to a specific fully-qualified table name.

        Returns
        -------
        List[ProductRecord] sorted by match quality (best first).
        """
        if not self._ready or not query.strip():
            return []

        q = query.strip().lower()

        def _filter_table(records: List[ProductRecord]) -> List[ProductRecord]:
            if not table:
                return records
            return [r for r in records if r.table == table]

        with self._lock:
            # Stage 1: exact phrase
            if q in self._by_phrase:
                hits = _filter_table(self._by_phrase[q])
                if hits:
                    return hits

            # Stage 2: extract number(s) from query and look up
            numbers = [m.group(1).lower() for m in _NUM_RE.finditer(q)]
            if numbers:
                candidates: Dict[str, Tuple[ProductRecord, int]] = {}
                for num in numbers:
                    for rec in self._by_number.get(num, []):
                        if table and rec.table != table:
                            continue
                        # Score by token overlap with query
                        score = _overlap_score(q, rec)
                        key = f"{rec.table}|{rec.col}|{rec.full_name}"
                        if key not in candidates or candidates[key][1] < score:
                            candidates[key] = (rec, score)
                if candidates:
                    return [r for r, _ in sorted(candidates.values(), key=lambda x: -x[1])]

            # Stage 3: token subset scan (slow path, used when query has no number)
            q_tokens = set(q.split())
            subset_hits: List[Tuple[ProductRecord, int]] = []
            for phrase, records in self._by_phrase.items():
                phrase_tokens = set(phrase.split())
                overlap = len(q_tokens & phrase_tokens)
                if overlap > 0 and q_tokens.issubset(phrase_tokens):
                    for rec in records:
                        if table and rec.table != table:
                            continue
                        subset_hits.append((rec, overlap))
            if subset_hits:
                return [r for r, _ in sorted(subset_hits, key=lambda x: -x[1])]

        return []

    def resolve(self, query: str, table: Optional[str] = None) -> Optional[str]:
        """
        Return the canonical full_name for a query fragment, or None if not found.

        Convenience wrapper around search() for use in the hallucination guard.
        """
        hits = self.search(query, table=table)
        return hits[0].full_name if hits else None

    # ── Utilities ──────────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        return self._ready

    def stats(self) -> dict:
        with self._lock:
            return {
                "ready":          self._ready,
                "total_products": len(self._all_records),
                "number_keys":    len(self._by_number),
                "phrase_keys":    len(self._by_phrase),
                "index_path":     str(self._path),
            }

    def correct_sql_values(self, sql: str, table: Optional[str] = None) -> str:
        """
        Scan WHERE-clause literals in product columns and replace them with
        the canonical DB name from this index, scoped to ``table``.

        Handles all common equality patterns:
          col = 'value'
          LOWER(col) = LOWER('value')
          LOWER(col) = 'value'
          col = LOWER('value')

        Examples
        --------
        WHERE Product_Name = 'LOCTITE 243'
            → WHERE Product_Name = 'LOCTITE 243 Threadlocker'
        WHERE LOWER(Product_Name) = LOWER('LOCTITE 243')
            → WHERE LOWER(Product_Name) = LOWER('LOCTITE 243 Threadlocker')
        """
        if not self._ready:
            return sql

        # Matches:
        #   [LOWER(] col [)] = [LOWER(] 'value' [)]
        # Groups: col_wrap (LOWER( or ''), col, val_wrap (LOWER( or ''), val
        _PATTERN = re.compile(
            r"(?P<col_wrap>LOWER\s*\(\s*)?"           # optional LOWER( before col
            r"(?P<col>`?\w+`?)"                        # column name
            r"(?(col_wrap)\s*\))"                      # closing ) only if LOWER( opened
            r"\s*=\s*"
            r"(?P<val_wrap>LOWER\s*\(\s*)?"           # optional LOWER( before value
            r"'(?P<val>[^']+)'"                        # the literal value
            r"(?(val_wrap)\s*\))",                     # closing ) only if LOWER( opened
            re.IGNORECASE,
        )

        def _replace(m: re.Match) -> str:
            col_raw = m.group("col").strip("`")
            val     = m.group("val")
            if col_raw.lower() not in _PRODUCT_COL_HINTS:
                return m.group(0)
            canonical = self.resolve(val, table=table)
            if not canonical or canonical.lower() == val.lower():
                return m.group(0)
            # Preserve the original match structure, only swap the literal
            return m.group(0).replace(f"'{val}'", f"'{canonical}'", 1)

        return _PATTERN.sub(_replace, sql)

    def dump_variants(self, limit: int = 20) -> List[dict]:
        """Return a sample of products with their indexed variants — useful for debugging."""
        with self._lock:
            sample = self._all_records[:limit]
        return [
            {
                "full_name":  r.full_name,
                "table":      r.table,
                "brand":      r.brand,
                "number":     r.number,
                "descriptor": r.descriptor,
                "variants":   r.variants,
            }
            for r in sample
        ]


# ── Scoring helper ─────────────────────────────────────────────────────────────

def _overlap_score(query: str, rec: ProductRecord) -> int:
    """Token overlap between query and record's brand + number + descriptor."""
    q_tokens  = set(query.split())
    rec_tokens = set(f"{rec.brand} {rec.number} {rec.descriptor}".split())
    return len(q_tokens & rec_tokens)


# ── Module-level singleton ─────────────────────────────────────────────────────

_instance: Optional[ProductIndex] = None


def init_product_index(
    data_service,
    index_dir: str = "",
    product_tables: Optional[set] = None,
    background: bool = True,
) -> ProductIndex:
    global _instance
    _instance = ProductIndex(index_dir=index_dir, product_tables=product_tables)
    _instance.load_or_build(data_service, background=background)
    return _instance


def get_product_index() -> Optional[ProductIndex]:
    return _instance
