"""Unit tests for services.rag.indexing.chunker (Chunker)."""

from unittest.mock import MagicMock, patch

import pytest

from services.rag.indexing.chunker import Chunker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_element(text: str) -> MagicMock:
    """Create a mock unstructured Element with the given text."""
    el = MagicMock()
    el.text = text
    return el


# ---------------------------------------------------------------------------
# clean_text
# ---------------------------------------------------------------------------

class TestCleanText:
    def test_passthrough_when_no_boilerplate(self):
        raw = "Tensile strength: 25 MPa after 24 h cure at 23 °C."
        assert Chunker.clean_text(raw) == raw

    def test_strips_henkel_footer(self):
        raw = (
            "Cure time: 15 minutes.\n"
            "# In case products are delivered by Henkel Colombiana\n"
            "some legal footer text"
        )
        result = Chunker.clean_text(raw)
        assert "Henkel Colombiana" not in result
        assert "Cure time: 15 minutes." in result

    def test_strips_direct_access_footer(self):
        raw = (
            "Viscosity: 1500 cP.\n"
            "For the most direct access to local sales and technical support "
            "visit our website."
        )
        result = Chunker.clean_text(raw)
        assert "most direct access" not in result
        assert "Viscosity: 1500 cP." in result

    def test_strips_leading_trailing_whitespace(self):
        assert Chunker.clean_text("  hello  ") == "hello"

    def test_empty_string_stays_empty(self):
        assert Chunker.clean_text("") == ""

    def test_case_insensitive_footer_removal(self):
        raw = "Intro text.\nFOR THE MOST DIRECT ACCESS TO LOCAL SALES AND TECHNICAL SUPPORT\nignore this"
        result = Chunker.clean_text(raw)
        assert "MOST DIRECT ACCESS" not in result
        assert "Intro text." in result


# ---------------------------------------------------------------------------
# is_excluded
# ---------------------------------------------------------------------------

class TestIsExcluded:
    def test_excluded_when_contains_conversions(self):
        assert Chunker.is_excluded("Unit Conversions table") is True

    def test_excluded_case_insensitive(self):
        assert Chunker.is_excluded("CONVERSIONS") is True

    def test_not_excluded_normal_text(self):
        assert Chunker.is_excluded("Cure time at 23 °C") is False

    def test_not_excluded_empty(self):
        assert Chunker.is_excluded("") is False


# ---------------------------------------------------------------------------
# chunk_texts
# ---------------------------------------------------------------------------

class TestChunkTexts:
    def test_filters_empty_strings(self):
        chunker = Chunker()
        result = chunker.chunk_texts(["", "  ", "valid text"])
        assert result == ["valid text"]

    def test_cleans_boilerplate(self):
        chunker = Chunker()
        raw = [
            "Good data.",
            "More data. # In case products are delivered by Henkel Colombiana\nfooter",
        ]
        result = chunker.chunk_texts(raw)
        assert len(result) == 2
        assert "Henkel Colombiana" not in result[1]

    def test_stops_on_exclusion_keyword(self):
        chunker = Chunker()
        texts = ["First chunk.", "conversions table here", "Third chunk."]
        result = chunker.chunk_texts(texts)
        # "conversions" chunk itself is dropped; third chunk should still appear
        # because chunk_texts does NOT break on exclusion — it just filters
        assert "First chunk." in result
        assert not any("conversions" in t.lower() for t in result)
        assert "Third chunk." in result

    def test_returns_empty_for_all_boilerplate(self):
        chunker = Chunker()
        result = chunker.chunk_texts(["", "  "])
        assert result == []


# ---------------------------------------------------------------------------
# chunk (integration with chunk_by_title mock)
# ---------------------------------------------------------------------------

class TestChunk:
    def _run_chunk(self, raw_texts: list[str], **kwargs) -> list[str]:
        chunker = Chunker(**kwargs)
        elements = [_make_element(t) for t in raw_texts]
        mock_chunks = [_make_element(t) for t in raw_texts]

        with patch(
            "services.rag.indexing.chunker.chunk_by_title",
            return_value=mock_chunks,
        ):
            return chunker.chunk(elements)

    def test_basic_pass_through(self):
        result = self._run_chunk(["Product description.", "Safety information."])
        assert result == ["Product description.", "Safety information."]

    def test_skips_empty_chunk_text(self):
        result = self._run_chunk(["Good text.", "", "More text."])
        assert "" not in result
        assert len(result) == 2

    def test_cuts_on_conversions_marker(self):
        result = self._run_chunk(
            ["Intro.", "Unit conversions table", "Appendix."]
        )
        # Processing stops at the 'conversions' chunk
        assert result == ["Intro."]

    def test_chunk_by_title_called_with_config(self):
        chunker = Chunker(combine_under_n_chars=500, max_characters=800)
        elements = [_make_element("text")]
        mock_chunks = [_make_element("text")]

        with patch(
            "services.rag.indexing.chunker.chunk_by_title",
            return_value=mock_chunks,
        ) as mock_cbt:
            chunker.chunk(elements)

        mock_cbt.assert_called_once_with(
            elements,
            combine_text_under_n_chars=500,
            max_characters=800,
        )

    def test_returns_empty_list_when_all_excluded(self):
        result = self._run_chunk(["conversions table"])
        assert result == []
