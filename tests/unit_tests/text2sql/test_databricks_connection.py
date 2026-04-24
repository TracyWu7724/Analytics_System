"""Unit tests for DatabricksService — Databricks connection and query methods."""

import os
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from services.text2sql.db.databricks_service import DatabricksService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_svc(hostname="host", client_id="id", secret="sec", http_path="/sql"):
    """Build a DatabricksService with controlled env and a temp local DB."""
    tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmpfile.close()
    svc = DatabricksService.__new__(DatabricksService)
    svc.server_hostname = hostname
    svc.client_id = client_id
    svc.client_secret = secret
    svc.http_path = http_path
    svc.local_db_path = tmpfile.name
    svc.init_local_db()
    return svc, tmpfile.name


def _mock_connection(rows, columns):
    """Return a context-manager mock connection that yields rows/columns."""
    cursor = MagicMock()
    cursor.description = [(col,) for col in columns]
    cursor.fetchmany.return_value = [tuple(row[c] for c in columns) for row in rows]
    cursor.__enter__ = lambda s: s
    cursor.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cursor


# ---------------------------------------------------------------------------
# __init__ — path wiring
# ---------------------------------------------------------------------------

class TestDatabricksServiceInit:
    def test_local_db_path_ends_with_data_db(self):
        with patch.dict(os.environ, {
            "DATABRICKS_SERVER_HOSTNAME": "h",
            "DATABRICKS_CLIENT_ID": "i",
            "DATABRICKS_CLIENT_SECRET": "s",
            "DATABRICKS_HTTP_PATH": "/p",
        }):
            svc = DatabricksService()
        assert svc.local_db_path.endswith("data.db")

    def test_local_db_path_is_absolute(self):
        with patch.dict(os.environ, {
            "DATABRICKS_SERVER_HOSTNAME": "h",
            "DATABRICKS_CLIENT_ID": "i",
            "DATABRICKS_CLIENT_SECRET": "s",
            "DATABRICKS_HTTP_PATH": "/p",
        }):
            svc = DatabricksService()
        assert os.path.isabs(svc.local_db_path)

    def test_missing_env_vars_still_constructs(self):
        with patch.dict(os.environ, {}, clear=True):
            svc = DatabricksService()  # should not raise
        assert svc.server_hostname is None


# ---------------------------------------------------------------------------
# execute_query — timeout and limit injection
# ---------------------------------------------------------------------------

class TestExecuteQuery:
    def setup_method(self):
        self.svc, self.db_path = _make_svc()

    def teardown_method(self):
        os.unlink(self.db_path)

    def test_returns_rows_as_list_of_dicts(self):
        rows = [{"id": 1, "val": "a"}, {"id": 2, "val": "b"}]
        conn, _ = _mock_connection(rows, ["id", "val"])
        with patch.object(self.svc, "get_databricks_connection", return_value=conn):
            result = self.svc.execute_query("SELECT * FROM t", timeout_seconds=5)
        assert result == rows

    def test_appends_default_limit_when_absent(self):
        rows = [{"n": 1}]
        conn, cursor = _mock_connection(rows, ["n"])
        with patch.object(self.svc, "get_databricks_connection", return_value=conn):
            self.svc.execute_query("SELECT n FROM t", timeout_seconds=5)
        executed_sql = cursor.execute.call_args[0][0]
        assert "LIMIT" in executed_sql.upper()

    def test_does_not_double_add_limit(self):
        rows = [{"n": 1}]
        conn, cursor = _mock_connection(rows, ["n"])
        with patch.object(self.svc, "get_databricks_connection", return_value=conn):
            self.svc.execute_query("SELECT n FROM t LIMIT 50", timeout_seconds=5)
        executed_sql = cursor.execute.call_args[0][0]
        assert executed_sql.upper().count("LIMIT") == 1

    def test_custom_limit_injected(self):
        rows = [{"n": 1}]
        conn, cursor = _mock_connection(rows, ["n"])
        with patch.object(self.svc, "get_databricks_connection", return_value=conn):
            self.svc.execute_query("SELECT n FROM t", timeout_seconds=5, custom_limit=250)
        executed_sql = cursor.execute.call_args[0][0]
        assert "250" in executed_sql

    def test_timeout_raises_timeout_error(self):
        def _slow_connect():
            conn = MagicMock()
            conn.__enter__ = lambda s: s
            conn.__exit__ = MagicMock(return_value=False)
            cursor = MagicMock()
            cursor.execute.side_effect = lambda q: time.sleep(10)
            cursor.__enter__ = lambda s: s
            cursor.__exit__ = MagicMock(return_value=False)
            conn.cursor.return_value = cursor
            return conn

        with patch.object(self.svc, "get_databricks_connection", side_effect=_slow_connect):
            with pytest.raises(TimeoutError, match="timed out"):
                self.svc.execute_query("SELECT 1", timeout_seconds=1)

    def test_query_error_bubbles_as_exception(self):
        conn, cursor = _mock_connection([], ["n"])
        cursor.execute.side_effect = RuntimeError("syntax error")
        with patch.object(self.svc, "get_databricks_connection", return_value=conn):
            with pytest.raises(Exception, match="syntax error"):
                self.svc.execute_query("BAD SQL", timeout_seconds=5)

    def test_no_description_returns_empty(self):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.description = None
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)
        with patch.object(self.svc, "get_databricks_connection", return_value=conn):
            result = self.svc.execute_query("SELECT 1", timeout_seconds=5)
        assert result == []


# ---------------------------------------------------------------------------
# get_table_names — qualification and error handling
# ---------------------------------------------------------------------------

class TestGetTableNames:
    def setup_method(self):
        self.svc, self.db_path = _make_svc()

    def teardown_method(self):
        os.unlink(self.db_path)

    def test_qualifies_unqualified_names(self):
        raw = [{"tableName": "sales"}, {"tableName": "orders"}]
        with patch.object(self.svc, "execute_query", return_value=raw):
            names = self.svc.get_table_names()
        assert all("swks_das_dev.gold." in n for n in names)

    def test_preserves_already_qualified_names(self):
        raw = [{"tableName": "swks_das_dev.gold.sales"}]
        with patch.object(self.svc, "execute_query", return_value=raw):
            names = self.svc.get_table_names()
        assert names == ["swks_das_dev.gold.sales"]

    def test_handles_table_name_column_key(self):
        raw = [{"table_name": "employees"}]
        with patch.object(self.svc, "execute_query", return_value=raw):
            names = self.svc.get_table_names()
        assert any("employees" in n for n in names)

    def test_returns_empty_list_on_error(self):
        with patch.object(self.svc, "execute_query", side_effect=RuntimeError("conn failed")):
            names = self.svc.get_table_names()
        assert names == []

    def test_count_matches_rows(self):
        raw = [{"tableName": f"tbl{i}"} for i in range(7)]
        with patch.object(self.svc, "execute_query", return_value=raw):
            names = self.svc.get_table_names()
        assert len(names) == 7


# ---------------------------------------------------------------------------
# test_connection — success / error / sample_tables cap
# ---------------------------------------------------------------------------

class TestTestConnection:
    def setup_method(self):
        self.svc, self.db_path = _make_svc()

    def teardown_method(self):
        os.unlink(self.db_path)

    def test_success_payload_structure(self):
        with patch.object(self.svc, "get_table_names", return_value=["a", "b", "c"]):
            result = self.svc.test_connection()
        assert result["status"] == "success"
        assert result["tables_count"] == 3
        assert "sample_tables" in result

    def test_sample_tables_capped_at_five(self):
        tables = [f"t{i}" for i in range(20)]
        with patch.object(self.svc, "get_table_names", return_value=tables):
            result = self.svc.test_connection()
        assert len(result["sample_tables"]) <= 5

    def test_error_returns_error_status(self):
        with patch.object(self.svc, "get_table_names", side_effect=RuntimeError("down")):
            result = self.svc.test_connection()
        assert result["status"] == "error"
        assert "down" in result["message"]
        assert result["tables_count"] == 0

    def test_empty_tables_succeeds(self):
        with patch.object(self.svc, "get_table_names", return_value=[]):
            result = self.svc.test_connection()
        assert result["status"] == "success"
        assert result["tables_count"] == 0


# ---------------------------------------------------------------------------
# get_table_schema — caching behaviour
# ---------------------------------------------------------------------------

class TestGetTableSchema:
    def setup_method(self):
        self.svc, self.db_path = _make_svc()

    def teardown_method(self):
        os.unlink(self.db_path)

    def test_returns_schema_from_execute_query(self):
        raw = [{"col_name": "id", "data_type": "int"}, {"col_name": "name", "data_type": "string"}]
        with patch.object(self.svc, "execute_query", return_value=raw):
            schema = self.svc.get_table_schema("gold.orders")
        assert schema == [{"name": "id", "type": "int"}, {"name": "name", "type": "string"}]

    def test_cached_result_not_refetched(self):
        raw = [{"col_name": "x", "data_type": "int"}]
        with patch.object(self.svc, "execute_query", return_value=raw) as mock_exec:
            self.svc.get_table_schema("gold.sales")
            self.svc.get_table_schema("gold.sales")
        assert mock_exec.call_count == 1

    def test_different_tables_fetched_independently(self):
        raw = [{"col_name": "x", "data_type": "int"}]
        with patch.object(self.svc, "execute_query", return_value=raw) as mock_exec:
            self.svc.get_table_schema("gold.t1")
            self.svc.get_table_schema("gold.t2")
        assert mock_exec.call_count == 2

    def test_returns_empty_list_on_error(self):
        with patch.object(self.svc, "execute_query", side_effect=RuntimeError("fail")):
            schema = self.svc.get_table_schema("gold.bad_table")
        assert schema == []
