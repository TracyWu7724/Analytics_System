"""Unit tests for pre_retrieval: QueryRewriter, QueryExpander, PreparedQuery."""

import pytest

from services.rag.pre_retrieval.query_rewrite import QueryRewriter
from services.rag.pre_retrieval.query_expansion import QueryExpander
from services.rag.rag_config import QueryPreparationConfig
from services.rag.rag_modeling import PreparedQuery


# ---------------------------------------------------------------------------
# QueryRewriter — normalize
# ---------------------------------------------------------------------------

class TestQueryRewriterNormalize:
    def test_lowercases_by_default(self):
        qr = QueryRewriter()
        assert qr.normalize("LOCTITE TDS") == "loctite tds"

    def test_collapses_whitespace(self):
        qr = QueryRewriter()
        assert qr.normalize("cure   time  at  23") == "cure time at 23"

    def test_strips_leading_trailing_whitespace(self):
        qr = QueryRewriter()
        assert qr.normalize("  hello world  ") == "hello world"

    def test_remove_punctuation_when_enabled(self):
        cfg = QueryPreparationConfig(remove_punctuation=True)
        qr = QueryRewriter(config=cfg)
        result = qr.normalize("What is the cure time?")
        assert "?" not in result

    def test_punctuation_kept_by_default(self):
        qr = QueryRewriter()
        assert "?" in qr.normalize("What is the cure time?")

    def test_no_lowercase_when_disabled(self):
        cfg = QueryPreparationConfig(lowercase=False)
        qr = QueryRewriter(config=cfg)
        assert qr.normalize("LOCTITE") == "LOCTITE"


# ---------------------------------------------------------------------------
# QueryRewriter — rewrite
# ---------------------------------------------------------------------------

class TestQueryRewriterRewrite:
    def test_uses_normalize_when_no_rewrite_fn(self):
        qr = QueryRewriter()
        assert qr.rewrite("CURE TIME") == "cure time"

    def test_applies_custom_rewrite_fn(self):
        qr = QueryRewriter(rewrite_fn=lambda q: q.replace("adhesive", "glue"))
        result = qr.rewrite("best adhesive for metal")
        assert "glue" in result
        assert "adhesive" not in result

    def test_normalizes_result_of_rewrite_fn(self):
        qr = QueryRewriter(rewrite_fn=lambda q: "  SOME TEXT  ")
        assert qr.rewrite("anything") == "some text"


# ---------------------------------------------------------------------------
# QueryExpander — expand
# ---------------------------------------------------------------------------

class TestQueryExpander:
    def test_returns_prepared_query(self):
        expander = QueryExpander()
        result = expander.expand("loctite tds")
        assert isinstance(result, PreparedQuery)

    def test_original_is_preserved_verbatim(self):
        expander = QueryExpander()
        result = expander.expand("  LOCTITE TDS  ")
        assert result.original == "LOCTITE TDS"

    def test_rewritten_is_normalized(self):
        expander = QueryExpander()
        result = expander.expand("  LOCTITE TDS  ")
        assert result.rewritten == "loctite tds"

    def test_synonym_expansion_tds(self):
        expander = QueryExpander()
        result = expander.expand("loctite tds")
        combined = " ".join(result.expansions)
        assert "technical data sheet" in combined or "datasheet" in combined

    def test_synonym_expansion_sds(self):
        expander = QueryExpander()
        result = expander.expand("product sds")
        combined = " ".join(result.expansions)
        assert "safety data sheet" in combined or "safety sheet" in combined

    def test_how_use_expansion(self):
        expander = QueryExpander()
        result = expander.expand("how to use loctite")
        combined = " ".join(result.expansions)
        assert "instructions to" in combined or "apply" in combined

    def test_what_is_expansion(self):
        expander = QueryExpander()
        result = expander.expand("what is viscosity")
        combined = " ".join(result.expansions)
        assert "definition of" in combined

    def test_quoted_phrase_included(self):
        expander = QueryExpander()
        result = expander.expand('"cure time" for loctite')
        assert "cure time" in result.expansions

    def test_max_expansions_capped(self):
        cfg = QueryPreparationConfig(max_expansions=2)
        expander = QueryExpander(config=cfg)
        result = expander.expand("loctite tds sds adhesive viscosity temperature")
        assert len(result.expansions) <= 2

    def test_no_duplicate_expansions(self):
        expander = QueryExpander()
        result = expander.expand("loctite spec specs tds")
        assert len(result.expansions) == len(set(result.expansions))


# ---------------------------------------------------------------------------
# PreparedQuery — all_queries
# ---------------------------------------------------------------------------

class TestPreparedQueryAllQueries:
    def test_deduplicates_original_and_rewritten(self):
        pq = PreparedQuery(original="cure time", rewritten="cure time", expansions=[])
        assert pq.all_queries() == ["cure time"]

    def test_order_original_rewritten_expansions(self):
        pq = PreparedQuery(
            original="what is the tds",
            rewritten="what is the tds",
            expansions=["what is the technical data sheet"],
        )
        queries = pq.all_queries()
        assert queries[0] == "what is the tds"
        assert "what is the technical data sheet" in queries

    def test_filters_empty_strings(self):
        pq = PreparedQuery(original="cure time", rewritten="cure time", expansions=["", "  "])
        assert "" not in pq.all_queries()
        assert "  " not in pq.all_queries()

    def test_all_unique_variants_included(self):
        pq = PreparedQuery(
            original="cure time",
            rewritten="cure time",
            expansions=["heat time", "operating temperature"],
        )
        queries = pq.all_queries()
        assert "heat time" in queries
        assert "operating temperature" in queries
        assert len(queries) == len(set(queries))
