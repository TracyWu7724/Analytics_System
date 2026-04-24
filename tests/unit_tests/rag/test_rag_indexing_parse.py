"""Unit tests for services.rag.indexing.parser (PdfParser)."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from services.rag.indexing.parser import PdfParser


# ---------------------------------------------------------------------------
# extract_product_id
# ---------------------------------------------------------------------------

class TestExtractProductId:
    def test_strips_locale_suffix(self):
        assert PdfParser.extract_product_id("LOCTITE-AA-332-en_GL.pdf") == "LOCTITE-AA-332"

    def test_no_locale_suffix(self):
        assert PdfParser.extract_product_id("LOCTITE-454.pdf") == "LOCTITE-454"

    def test_numeric_only_product(self):
        assert PdfParser.extract_product_id("12345-de_DE.pdf") == "12345"

    def test_falls_back_to_basename_when_no_match(self):
        # lowercase filename won't match the uppercase regex — falls back to basename
        result = PdfParser.extract_product_id("lowercase-product.pdf")
        assert result == "lowercase-product"

    def test_hyphenated_multi_segment(self):
        assert PdfParser.extract_product_id("LOCTITE-AA-332-B-en_US.pdf") == "LOCTITE-AA-332-B"


# ---------------------------------------------------------------------------
# product_uuid
# ---------------------------------------------------------------------------

class TestProductUuid:
    def test_returns_hex_string(self):
        uuid = PdfParser.product_uuid("LOCTITE-454")
        assert all(c in "0123456789abcdef" for c in uuid)

    def test_default_length_is_10(self):
        assert len(PdfParser.product_uuid("LOCTITE-454")) == 10

    def test_custom_length(self):
        assert len(PdfParser.product_uuid("LOCTITE-454", length=6)) == 6

    def test_deterministic(self):
        assert PdfParser.product_uuid("LOCTITE-454") == PdfParser.product_uuid("LOCTITE-454")

    def test_different_products_differ(self):
        assert PdfParser.product_uuid("LOCTITE-454") != PdfParser.product_uuid("LOCTITE-680")


# ---------------------------------------------------------------------------
# pdf_files
# ---------------------------------------------------------------------------

class TestPdfFiles:
    def test_returns_sorted_pdf_filenames(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["b.pdf", "a.pdf", "c.PDF"]:
                open(os.path.join(tmpdir, name), "w").close()
            open(os.path.join(tmpdir, "readme.txt"), "w").close()

            result = PdfParser().pdf_files(tmpdir)

        assert result == ["a.pdf", "b.pdf", "c.PDF"]

    def test_empty_directory_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert PdfParser().pdf_files(tmpdir) == []

    def test_raises_for_missing_directory(self):
        with pytest.raises(FileNotFoundError):
            PdfParser().pdf_files("/does/not/exist")


# ---------------------------------------------------------------------------
# parse (mocked partition_pdf)
# ---------------------------------------------------------------------------

class TestParse:
    def test_calls_partition_pdf_with_correct_args(self):
        parser = PdfParser(strategy="fast", infer_table_structure=False)
        mock_elements = [MagicMock(), MagicMock()]

        with patch(
            "services.rag.indexing.parser.partition_pdf",
            return_value=mock_elements,
        ) as mock_part:
            result = parser.parse("/some/file.pdf")

        mock_part.assert_called_once_with(
            filename="/some/file.pdf",
            strategy="fast",
            infer_table_structure=False,
            extract_images_in_pdf=False,
        )
        assert result is mock_elements

    def test_default_strategy_is_hi_res(self):
        parser = PdfParser()
        with patch("services.rag.indexing.parser.partition_pdf", return_value=[]) as mock_part:
            parser.parse("/x.pdf")
        _, kwargs = mock_part.call_args
        assert kwargs["strategy"] == "hi_res"
        assert kwargs["infer_table_structure"] is True


# ---------------------------------------------------------------------------
# parse_directory (mocked parse)
# ---------------------------------------------------------------------------

class TestParseDirectory:
    def test_parses_all_pdfs_in_directory(self):
        parser = PdfParser()

        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["A.pdf", "B.pdf"]:
                open(os.path.join(tmpdir, name), "w").close()

            fake_elements = [MagicMock()]
            with patch.object(parser, "parse", return_value=fake_elements) as mock_parse:
                result = parser.parse_directory(tmpdir)

        assert set(result.keys()) == {"A.pdf", "B.pdf"}
        assert result["A.pdf"] is fake_elements
        assert mock_parse.call_count == 2
