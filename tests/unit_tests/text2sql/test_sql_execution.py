"""Unit tests for sql_correction, upload_service, and local SQLite execution."""

import os
import sqlite3
import tempfile

import pandas as pd
import pytest

from services.text2sql.generation.sql_correction import clean_sql_query, validate_sql_server_query
from services.text2sql.db.upload_service import UploadService, clean_column_name
from services.text2sql.db.databricks_service import DatabricksService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service_with_temp_db() -> tuple[DatabricksService, str]:
    """Return a DatabricksService pointing at a fresh temp SQLite database."""
    tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmpfile.close()
    svc = DatabricksService.__new__(DatabricksService)
    svc.local_db_path = tmpfile.name
    svc.server_hostname = None
    svc.client_id = None
    svc.client_secret = None
    svc.http_path = None
    svc.init_local_db()
    return svc, tmpfile.name


# ---------------------------------------------------------------------------
# clean_column_name
# ---------------------------------------------------------------------------

class TestCleanColumnName:
    def test_passthrough_valid_name(self):
        assert clean_column_name("Revenue") == "Revenue"

    def test_replaces_spaces_with_underscore(self):
        assert clean_column_name("Order ID") == "Order_ID"

    def test_replaces_special_chars(self):
        assert clean_column_name("Revenue ($)") == "Revenue____"

    def test_strips_leading_trailing_underscores(self):
        result = clean_column_name("  Name  ")
        assert not result.startswith("_")
        assert not result.endswith("_")

    def test_prepends_col_when_starts_with_digit(self):
        assert clean_column_name("1stColumn").startswith("col_")

    def test_empty_string_returns_unnamed_column(self):
        assert clean_column_name("") == "unnamed_column"

    def test_only_special_chars_returns_unnamed_column(self):
        assert clean_column_name("!@#$%") == "unnamed_column"


# ---------------------------------------------------------------------------
# validate_sql_server_query
# ---------------------------------------------------------------------------

class TestValidateSqlServerQuery:
    def test_select_passes(self):
        sql = "SELECT TOP 10 * FROM sales"
        assert validate_sql_server_query(sql) == sql

    def test_drop_table_raises(self):
        with pytest.raises(ValueError, match="Disallowed"):
            validate_sql_server_query("DROP TABLE users")

    def test_truncate_raises(self):
        with pytest.raises(ValueError, match="Disallowed"):
            validate_sql_server_query("TRUNCATE TABLE logs")

    def test_delete_from_raises(self):
        with pytest.raises(ValueError, match="Disallowed"):
            validate_sql_server_query("DELETE FROM orders WHERE id=1")

    def test_insert_into_raises(self):
        with pytest.raises(ValueError, match="Disallowed"):
            validate_sql_server_query("INSERT INTO t VALUES (1)")

    def test_xp_cmdshell_raises(self):
        with pytest.raises(ValueError, match="Disallowed"):
            validate_sql_server_query("EXEC xp_cmdshell('cmd')")

    def test_case_insensitive(self):
        with pytest.raises(ValueError):
            validate_sql_server_query("drop table foo")


# ---------------------------------------------------------------------------
# clean_sql_query
# ---------------------------------------------------------------------------

class TestCleanSqlQuery:
    def test_strips_markdown_sql_fence(self):
        raw = "```sql\nSELECT * FROM t\n```"
        result = clean_sql_query(raw)
        assert "```" not in result
        assert "SELECT" in result

    def test_strips_generic_fence(self):
        raw = "```SELECT 1```"
        result = clean_sql_query(raw)
        assert "```" not in result

    def test_removes_trailing_semicolon(self):
        result = clean_sql_query("SELECT 1;")
        assert not result.endswith(";")

    def test_collapses_whitespace(self):
        result = clean_sql_query("SELECT   *   FROM   t")
        assert "  " not in result

    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError, match="Empty"):
            clean_sql_query("")

    def test_raises_on_too_short_after_cleaning(self):
        with pytest.raises(ValueError):
            clean_sql_query("```\n\n```")

    def test_raises_on_disallowed_operation(self):
        with pytest.raises(ValueError):
            clean_sql_query("DROP TABLE users")

    def test_valid_query_returned(self):
        result = clean_sql_query("  SELECT TOP 5 * FROM sales  ")
        assert result.startswith("SELECT")


# ---------------------------------------------------------------------------
# DatabricksService — local SQLite methods
# ---------------------------------------------------------------------------

class TestDatabricksServiceLocalDb:
    def setup_method(self):
        self.svc, self.db_path = _make_service_with_temp_db()

    def teardown_method(self):
        os.unlink(self.db_path)

    def test_init_creates_schema_tables(self):
        conn = sqlite3.connect(self.db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "recent_queries" in tables
        assert "table_metadata" in tables

    def test_save_and_get_recent_queries(self):
        self.svc.save_query_to_history("show revenue by region")
        self.svc.save_query_to_history("list top products")
        result = self.svc.get_recent_queries(limit=5)
        assert len(result) == 2
        texts = [r["query_text"] for r in result]
        assert "show revenue by region" in texts

    def test_recent_queries_ordered_descending(self):
        for q in ["first", "second", "third"]:
            self.svc.save_query_to_history(q)
        result = self.svc.get_recent_queries(limit=3)
        assert result[0]["query_text"] == "third"

    def test_get_uploaded_tables_empty_initially(self):
        assert self.svc.get_uploaded_tables() == []

    def test_handle_uploaded_file_stores_dataframe(self):
        df = pd.DataFrame({"col_a": [1, 2, 3], "col_b": ["x", "y", "z"]})
        result = self.svc.handle_uploaded_file(df, "uploaded_test", "test.csv", ".csv")
        assert result["success"] is True
        assert result["row_count"] == 3

    def test_get_uploaded_tables_after_insert(self):
        df = pd.DataFrame({"val": range(5)})
        self.svc.handle_uploaded_file(df, "uploaded_sample", "sample.csv", ".csv")
        tables = self.svc.get_uploaded_tables()
        assert len(tables) == 1
        assert tables[0]["name"] == "uploaded_sample"
        assert tables[0]["is_uploaded"] is True
        assert tables[0]["row_count"] == 5

    def test_delete_uploaded_table(self):
        df = pd.DataFrame({"val": [1, 2]})
        self.svc.handle_uploaded_file(df, "uploaded_del", "del.csv", ".csv")
        result = self.svc.delete_uploaded_table("uploaded_del")
        assert result["success"] is True
        assert self.svc.get_uploaded_tables() == []

    def test_delete_nonexistent_table_fails(self):
        result = self.svc.delete_uploaded_table("uploaded_ghost")
        assert result["success"] is False

    def test_query_uploaded_table(self):
        df = pd.DataFrame({"score": [10, 20, 30]})
        self.svc.handle_uploaded_file(df, "uploaded_scores", "scores.csv", ".csv")
        rows = self.svc.query_uploaded_table("SELECT score FROM uploaded_scores ORDER BY score")
        assert [r["score"] for r in rows] == [10, 20, 30]

    def test_get_table_metadata_returns_filename(self):
        df = pd.DataFrame({"x": [1]})
        self.svc.handle_uploaded_file(df, "uploaded_meta", "myfile.xlsx", ".xlsx")
        meta = self.svc.get_table_metadata("uploaded_meta")
        assert meta.get("original_filename") == "myfile.xlsx"
        assert meta.get("file_extension") == ".xlsx"

    def test_get_table_metadata_missing_returns_empty(self):
        assert self.svc.get_table_metadata("uploaded_missing") == {}


# ---------------------------------------------------------------------------
# UploadService.process_uploaded_file
# ---------------------------------------------------------------------------

class TestUploadService:
    def setup_method(self):
        self.svc, self.db_path = _make_service_with_temp_db()
        self.upload_svc = UploadService(self.svc)

    def teardown_method(self):
        os.unlink(self.db_path)

    def test_process_csv_file(self):
        df = pd.DataFrame({"Product": ["A", "B"], "Units Sold": [10, 20]})
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            df.to_csv(f, index=False)
            path = f.name
        try:
            result = self.upload_svc.process_uploaded_file(path, "sales.csv")
            assert result["success"] is True
            assert result["row_count"] == 2
            assert "Units_Sold" in result["columns"]
        finally:
            os.unlink(path)

    def test_process_excel_file(self):
        df = pd.DataFrame({"Name": ["Alice", "Bob"], "Score": [95, 88]})
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = f.name
        df.to_excel(path, index=False)
        try:
            result = self.upload_svc.process_uploaded_file(path, "employees.xlsx")
            assert result["success"] is True
            assert result["row_count"] == 2
        finally:
            os.unlink(path)

    def test_unsupported_format_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            path = f.name
        try:
            with pytest.raises(ValueError, match="Unsupported"):
                self.upload_svc.process_uploaded_file(path, "data.txt")
        finally:
            os.unlink(path)

    def test_duplicate_columns_deduped(self):
        df = pd.DataFrame([[1, 2, 3]], columns=["A", "A", "B"])
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            df.to_csv(f, index=False)
            path = f.name
        try:
            result = self.upload_svc.process_uploaded_file(path, "dup.csv")
            cols = result["columns"]
            assert len(cols) == len(set(cols)), "Duplicate column names not deduped"
        finally:
            os.unlink(path)

    def test_get_uploaded_table_columns(self):
        df = pd.DataFrame({"foo": [1], "bar": [2]})
        self.svc.handle_uploaded_file(df, "uploaded_cols", "cols.csv", ".csv")
        cols = self.upload_svc.get_uploaded_table_columns("uploaded_cols", self.db_path)
        assert "foo" in cols
        assert "bar" in cols
