"""Small in-memory TTL cache for text2sql service helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheEntry:
    value: Any
    expires_at: float

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


class CacheService:
    """Simple process-local cache for metadata-heavy lookups."""

    def __init__(self):
        self._query_results: dict[tuple[str, int | None], CacheEntry] = {}
        self._table_lists: dict[bool, CacheEntry] = {}
        self._table_schemas: dict[str, CacheEntry] = {}

    def _get(self, bucket: dict[Any, CacheEntry], key: Any):
        entry = bucket.get(key)
        if entry is None:
            return None
        if entry.expired:
            bucket.pop(key, None)
            return None
        return entry.value

    def _set(self, bucket: dict[Any, CacheEntry], key: Any, value: Any, ttl: int):
        bucket[key] = CacheEntry(value=value, expires_at=time.time() + ttl)

    def get_query_result(self, query: str, limit: int | None = None):
        return self._get(self._query_results, (query, limit))

    def set_query_result(self, query: str, result, limit: int | None = None, ttl: int = 60):
        self._set(self._query_results, (query, limit), result, ttl)

    def get_table_list(self, include_sql_server: bool = False):
        return self._get(self._table_lists, include_sql_server)

    def set_table_list(self, tables, include_sql_server: bool = False, ttl: int = 300):
        self._set(self._table_lists, include_sql_server, tables, ttl)

    def get_table_schema(self, table_name: str):
        return self._get(self._table_schemas, table_name)

    def set_table_schema(self, table_name: str, schema, ttl: int = 300):
        self._set(self._table_schemas, table_name, schema, ttl)

    def invalidate_table_list(self):
        self._table_lists.clear()

    def invalidate_table_schema(self, table_name: str | None = None):
        if table_name is None:
            self._table_schemas.clear()
            return
        self._table_schemas.pop(table_name, None)


db_cache = CacheService()
