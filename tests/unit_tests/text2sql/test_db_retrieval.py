"""Unit tests for CacheService, table_matching, and history_question_retrieval."""

import time
from unittest.mock import MagicMock

import pytest

from services.text2sql.cache_service import CacheService
from services.text2sql.retrieval.history_question_retrieval import get_relevant_query_history
from services.text2sql.retrieval.table_matching import (
    extract_table_name_from_question,
    find_best_table_match,
    get_all_available_tables,
    get_relevant_tables,
    invalidate_table_cache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(uploaded=None, databricks=None):
    """Build a mock data service with configurable table lists."""
    svc = MagicMock()
    svc.get_uploaded_tables.return_value = uploaded or []
    svc.get_table_names.return_value = databricks or []
    svc.get_recent_queries.return_value = []
    return svc


def _uploaded_table(name: str, filename: str = "") -> dict:
    return {"name": name, "original_filename": filename, "is_uploaded": True}


def _recent_query(text: str) -> dict:
    return {"query_text": text, "created_at": "2024-01-01"}


# ---------------------------------------------------------------------------
# CacheService
# ---------------------------------------------------------------------------

class TestCacheService:
    def setup_method(self):
        self.cache = CacheService()

    def test_get_returns_none_before_set(self):
        assert self.cache.get_query_result("SELECT 1") is None

    def test_set_and_get_query_result(self):
        self.cache.set_query_result("SELECT 1", [{"col": 1}], ttl=60)
        assert self.cache.get_query_result("SELECT 1") == [{"col": 1}]

    def test_query_result_expires(self):
        self.cache.set_query_result("SELECT 2", [{"col": 2}], ttl=0)
        time.sleep(0.01)
        assert self.cache.get_query_result("SELECT 2") is None

    def test_set_and_get_table_list(self):
        tables = [{"full_name": "gold.sales"}]
        self.cache.set_table_list(tables, include_sql_server=True, ttl=60)
        assert self.cache.get_table_list(include_sql_server=True) == tables

    def test_table_list_keyed_by_include_sql_server(self):
        self.cache.set_table_list(["a"], include_sql_server=False, ttl=60)
        self.cache.set_table_list(["a", "b"], include_sql_server=True, ttl=60)
        assert self.cache.get_table_list(include_sql_server=False) == ["a"]
        assert self.cache.get_table_list(include_sql_server=True) == ["a", "b"]

    def test_invalidate_table_list(self):
        self.cache.set_table_list(["x"], ttl=60)
        self.cache.invalidate_table_list()
        assert self.cache.get_table_list() is None

    def test_set_and_get_table_schema(self):
        schema = [{"name": "id", "type": "int"}]
        self.cache.set_table_schema("sales", schema, ttl=60)
        assert self.cache.get_table_schema("sales") == schema

    def test_invalidate_specific_table_schema(self):
        self.cache.set_table_schema("sales", [{"name": "id"}], ttl=60)
        self.cache.set_table_schema("orders", [{"name": "oid"}], ttl=60)
        self.cache.invalidate_table_schema("sales")
        assert self.cache.get_table_schema("sales") is None
        assert self.cache.get_table_schema("orders") is not None

    def test_invalidate_all_schemas(self):
        self.cache.set_table_schema("t1", [], ttl=60)
        self.cache.set_table_schema("t2", [], ttl=60)
        self.cache.invalidate_table_schema()
        assert self.cache.get_table_schema("t1") is None
        assert self.cache.get_table_schema("t2") is None

    def test_expired_entry_removed_from_bucket(self):
        self.cache.set_query_result("q", "val", ttl=0)
        time.sleep(0.01)
        self.cache.get_query_result("q")
        # After expiry read, bucket should be clean
        assert "q" not in {k[0] for k in self.cache._query_results}


# ---------------------------------------------------------------------------
# get_all_available_tables
# ---------------------------------------------------------------------------

class TestGetAllAvailableTables:
    def setup_method(self):
        # Clear the module-level cache before each test
        invalidate_table_cache()

    def test_includes_uploaded_tables(self):
        svc = _make_service(uploaded=[_uploaded_table("uploaded_sales", "sales.csv")])
        tables = get_all_available_tables(svc)
        names = [t["full_name"] for t in tables]
        assert "uploaded_sales" in names

    def test_includes_databricks_tables(self):
        svc = _make_service(databricks=["swks_das_dev.gold.orders"])
        tables = get_all_available_tables(svc)
        names = [t["full_name"] for t in tables]
        assert "swks_das_dev.gold.orders" in names

    def test_uploaded_source_label(self):
        svc = _make_service(uploaded=[_uploaded_table("uploaded_emp")])
        tables = get_all_available_tables(svc)
        uploaded = next(t for t in tables if t["full_name"] == "uploaded_emp")
        assert uploaded["source"] == "uploaded"

    def test_databricks_source_label(self):
        svc = _make_service(databricks=["gold.sales"])
        tables = get_all_available_tables(svc)
        db_table = next(t for t in tables if "gold.sales" in t["full_name"])
        assert db_table["source"] == "databricks"

    def test_cached_result_not_refetched(self):
        svc = _make_service(uploaded=[_uploaded_table("uploaded_x")])
        get_all_available_tables(svc)
        get_all_available_tables(svc)
        # Service should only have been called once (second call uses cache)
        assert svc.get_uploaded_tables.call_count == 1

    def test_empty_service_returns_empty(self):
        svc = _make_service()
        assert get_all_available_tables(svc) == []


# ---------------------------------------------------------------------------
# get_relevant_tables
# ---------------------------------------------------------------------------

class TestGetRelevantTables:
    def setup_method(self):
        invalidate_table_cache()

    def test_returns_up_to_limit(self):
        svc = _make_service(
            uploaded=[_uploaded_table(f"uploaded_t{i}") for i in range(10)]
        )
        results = get_relevant_tables("any question", svc, limit=3)
        assert len(results) <= 3

    def test_sorted_by_score_descending(self):
        svc = _make_service(
            uploaded=[
                _uploaded_table("uploaded_employee_directory", "employee_directory.xlsx"),
                _uploaded_table("uploaded_sales_data", "sales_data.csv"),
            ]
        )
        results = get_relevant_tables("employee salaries", svc, limit=5)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_best_match_ranks_first(self):
        invalidate_table_cache()
        svc = _make_service(
            uploaded=[
                _uploaded_table("uploaded_inventory_tracker", "inventory.csv"),
                _uploaded_table("uploaded_employee_directory", "employee.csv"),
            ]
        )
        results = get_relevant_tables("inventory stock levels", svc, limit=2)
        assert "inventory" in results[0]["full_name"]

    def test_score_field_present(self):
        svc = _make_service(uploaded=[_uploaded_table("uploaded_sales")])
        results = get_relevant_tables("sales data", svc)
        assert all("score" in r for r in results)


# ---------------------------------------------------------------------------
# find_best_table_match / extract_table_name_from_question
# ---------------------------------------------------------------------------

class TestTableExtraction:
    def setup_method(self):
        invalidate_table_cache()

    def test_find_best_match_returns_string(self):
        svc = _make_service(uploaded=[_uploaded_table("uploaded_sales")])
        result = find_best_table_match("show sales", svc)
        assert isinstance(result, str)

    def test_find_best_match_none_when_no_tables(self):
        svc = _make_service()
        assert find_best_table_match("show data", svc) is None

    def test_extract_falls_back_to_default(self):
        svc = _make_service()
        result = extract_table_name_from_question("some query", svc)
        assert result == "swks_das_dev.gold"

    def test_extract_returns_best_match_when_available(self):
        invalidate_table_cache()
        svc = _make_service(uploaded=[_uploaded_table("uploaded_sales_data")])
        result = extract_table_name_from_question("show sales", svc)
        assert "sales" in result


# ---------------------------------------------------------------------------
# get_relevant_query_history
# ---------------------------------------------------------------------------

class TestGetRelevantQueryHistory:
    def _svc(self, queries: list[str]):
        svc = MagicMock()
        svc.get_recent_queries.return_value = [_recent_query(q) for q in queries]
        return svc

    def test_returns_up_to_limit(self):
        svc = self._svc(["q1", "q2", "q3", "q4", "q5"])
        result = get_relevant_query_history("some question", svc, limit=2)
        assert len(result) <= 2

    def test_sorted_by_score_descending(self):
        svc = self._svc([
            "show total revenue by category",
            "list employee salaries",
            "show revenue breakdown",
        ])
        result = get_relevant_query_history("revenue by category", svc, limit=3)
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_best_match_is_most_similar(self):
        svc = self._svc([
            "show total revenue by product category",
            "list all employees in engineering",
        ])
        result = get_relevant_query_history("revenue by category", svc, limit=2)
        assert "revenue" in result[0]["query_text"].lower()

    def test_empty_history_returns_empty(self):
        svc = self._svc([])
        assert get_relevant_query_history("anything", svc) == []

    def test_result_contains_query_text_and_score(self):
        svc = self._svc(["show sales data"])
        result = get_relevant_query_history("sales", svc, limit=1)
        assert "query_text" in result[0]
        assert "score" in result[0]

    def test_skips_entries_without_query_text(self):
        svc = MagicMock()
        svc.get_recent_queries.return_value = [
            {"query_text": "", "created_at": "2024-01-01"},
            {"query_text": "valid query", "created_at": "2024-01-01"},
        ]
        result = get_relevant_query_history("valid", svc, limit=5)
        assert all(r["query_text"] for r in result)
