"""Unit tests for services.text2sql.generation.sql_generation."""

from unittest.mock import MagicMock, patch

import pytest

from backend.services.text2sql.generation.sql_generation import (
    detect_large_dataset_request,
    generate_sql,
)


# ---------------------------------------------------------------------------
# detect_large_dataset_request
# ---------------------------------------------------------------------------

class TestDetectLargeDatasetRequest:
    def test_all_rows_keyword_returns_large(self):
        is_large, limit, _ = detect_large_dataset_request("show me all rows")
        assert is_large is True
        assert limit is None  # no cap when asking for everything

    def test_all_data_keyword(self):
        is_large, _, _ = detect_large_dataset_request("export all data from sales")
        assert is_large is True

    def test_everything_keyword(self):
        is_large, _, _ = detect_large_dataset_request("get everything")
        assert is_large is True

    def test_entire_table_keyword(self):
        is_large, _, _ = detect_large_dataset_request("give me the entire table")
        assert is_large is True

    def test_small_explicit_limit_not_large(self):
        is_large, limit, _ = detect_large_dataset_request("show top 500 records")
        assert is_large is False
        assert limit == 500

    def test_large_explicit_limit_flagged(self):
        is_large, limit, _ = detect_large_dataset_request("show me 2000 rows")
        assert is_large is True
        assert limit == 2000

    def test_very_large_explicit_limit(self):
        is_large, limit, timeout = detect_large_dataset_request("get 15000 records")
        assert is_large is True
        assert limit == 15000
        assert timeout >= 120

    def test_normal_question_not_large(self):
        is_large, limit, _ = detect_large_dataset_request("what is total revenue by category?")
        assert is_large is False

    def test_first_n_pattern(self):
        _, limit, _ = detect_large_dataset_request("show first 50 results")
        assert limit == 50

    def test_timeout_increases_with_size(self):
        _, _, timeout_small = detect_large_dataset_request("show 500 rows")
        _, _, timeout_large = detect_large_dataset_request("show 6000 rows")
        assert timeout_large > timeout_small

    def test_returns_tuple_of_three(self):
        result = detect_large_dataset_request("any question")
        assert len(result) == 3

    def test_all_rows_has_large_timeout(self):
        _, _, timeout = detect_large_dataset_request("all rows please")
        assert timeout >= 60


# ---------------------------------------------------------------------------
# generate_sql — mocked LLM
# ---------------------------------------------------------------------------

class TestGenerateSql:
    def _mock_llm(self, sql: str):
        mock = MagicMock()
        mock.invoke.return_value.content = sql
        return mock

    def test_calls_llm_and_returns_content(self):
        expected_sql = "SELECT * FROM sales LIMIT 100"
        with patch("services.text2sql.generation.sql_generation.get_llm", return_value=self._mock_llm(expected_sql)):
            result = generate_sql("show sales", "sales")
        assert result == expected_sql

    def test_uploaded_table_uses_sqlite_prompt(self):
        with patch("services.text2sql.generation.sql_generation.get_llm") as mock_get_llm:
            mock_llm = self._mock_llm("SELECT * FROM uploaded_sales")
            mock_get_llm.return_value = mock_llm
            generate_sql("show data", "uploaded_sales_data", llm_model="gemini-2.5-flash")

        prompt = mock_llm.invoke.call_args[0][0]
        assert "SQLite" in prompt
        assert "uploaded_sales_data" in prompt

    def test_non_uploaded_table_uses_tsql_prompt(self):
        with patch("services.text2sql.generation.sql_generation.get_llm") as mock_get_llm:
            mock_llm = self._mock_llm("SELECT TOP 10 * FROM gold.sales")
            mock_get_llm.return_value = mock_llm
            generate_sql("show data", "swks_das_dev.gold.sales")

        prompt = mock_llm.invoke.call_args[0][0]
        assert "T-SQL" in prompt or "SQL Server" in prompt

    def test_columns_list_included_in_prompt(self):
        cols = ["Order_ID", "Revenue", "Category"]
        with patch("services.text2sql.generation.sql_generation.get_llm") as mock_get_llm:
            mock_llm = self._mock_llm("SELECT Order_ID FROM uploaded_t")
            mock_get_llm.return_value = mock_llm
            generate_sql("show orders", "uploaded_t", columns_list=cols)

        prompt = mock_llm.invoke.call_args[0][0]
        for col in cols:
            assert col in prompt

    def test_custom_limit_passed_to_prompt(self):
        with patch("services.text2sql.generation.sql_generation.get_llm") as mock_get_llm:
            mock_llm = self._mock_llm("SELECT * FROM t LIMIT 5000")
            mock_get_llm.return_value = mock_llm
            generate_sql("show lots of data", "uploaded_t", custom_limit=5000)

        prompt = mock_llm.invoke.call_args[0][0]
        assert "5000" in prompt

    def test_llm_model_forwarded(self):
        with patch("services.text2sql.generation.sql_generation.get_llm") as mock_get_llm:
            mock_llm = self._mock_llm("SELECT 1")
            mock_get_llm.return_value = mock_llm
            generate_sql("test", "t", llm_model="gpt-4o")
        mock_get_llm.assert_called_once_with("gpt-4o")
