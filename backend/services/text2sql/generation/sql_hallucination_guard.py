"""
sql_hallucination_guard.py — Self-correction layer for Text2SQL hallucinations.

Covers four hallucination types:
  1. Schema       — LLM uses columns/tables that don't exist in the schema
  2. Logical      — SQL is syntactically valid but semantically wrong
  3. Execution    — SQL fails at runtime (handled upstream by retry loop)
  4. Empty result — Query returns 0 rows when data should exist

Each check returns a (passed: bool, error_hint: str) tuple.
The error_hint is injected into the next generation attempt.

Traces are written to logs/hallucination_traces.jsonl for analysis.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..db.databricks_service import DatabricksService
    from ..indexing.inverted_index import InvertedIndex

# ── Trace file ────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parents[5]   # project root
_TRACE_FILE = _ROOT / "logs" / "hallucination_traces.jsonl"
_TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _write_trace(record: dict) -> None:
    """Append a hallucination event to the JSONL trace file."""
    try:
        with open(_TRACE_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _trace(
    hallucination_type: str,
    question: str,
    sql: str,
    detail: str,
    session_id: str = "",
    user_id: str = "",
) -> None:
    _write_trace({
        "timestamp": datetime.utcnow().isoformat(),
        "session_id": session_id,
        "user_id": user_id,
        "hallucination_type": hallucination_type,
        "question": question,
        "sql": sql,
        "detail": detail,
    })


# ── SQL keyword / function name exclusion list ────────────────────────────────

_SQL_KEYWORDS = {
    "select", "from", "where", "group", "by", "order", "having", "join",
    "left", "right", "inner", "outer", "cross", "full", "on", "as", "and",
    "or", "not", "in", "like", "between", "is", "null", "distinct", "limit",
    "offset", "top", "union", "all", "with", "asc", "desc", "case", "when",
    "then", "else", "end", "exists", "any", "some", "into", "values",
    "count", "sum", "avg", "min", "max", "coalesce", "isnull", "nvl",
    "ifnull", "cast", "convert", "trim", "upper", "lower", "substring",
    "substr", "len", "length", "round", "floor", "ceil", "ceiling",
    "year", "month", "day", "date", "now", "current_date", "current_timestamp",
    "datediff", "dateadd", "extract", "to_date", "to_char", "replace",
    "concat", "string_agg", "listagg", "row_number", "rank", "dense_rank",
    "over", "partition", "rows", "range", "preceding", "following",
    "unbounded", "current", "row", "fetch", "next", "only", "percent",
    "true", "false", "null", "integer", "varchar", "text", "float",
    "boolean", "timestamp", "interval", "array", "struct",
    # Spark SQL / Databricks-specific functions
    "collect_set", "collect_list", "array_agg", "approx_count_distinct",
    "percentile", "percentile_approx", "explode", "explode_outer",
    "posexplode", "flatten", "array_distinct", "array_sort", "array_union",
    "array_intersect", "array_except", "array_contains", "array_size",
    "size", "map", "map_keys", "map_values", "named_struct", "to_json",
    "from_json", "parse_json", "schema_of_json", "get_json_object",
    "json_tuple", "transform", "filter", "aggregate", "zip_with",
    "forall", "exists", "element_at", "first", "last", "nth_value",
    "lag", "lead", "cume_dist", "ntile", "percent_rank",
    "date_trunc", "date_format", "date_add", "date_sub", "months_between",
    "add_months", "next_day", "last_day", "trunc", "unix_timestamp",
    "from_unixtime", "to_timestamp", "quarter", "weekofyear", "dayofweek",
    "dayofyear", "hour", "minute", "second",
    "if", "iff", "nvl2", "nullif", "decode", "greatest", "least",
    "lpad", "rpad", "ltrim", "rtrim", "split", "regexp_extract",
    "regexp_replace", "instr", "locate", "initcap", "base64", "unbase64",
    "hash", "md5", "sha1", "sha2", "crc32", "uuid", "monotonically_increasing_id",
    "spark_partition_id", "input_file_name", "current_user", "current_schema",
}


def _strip_literals(sql: str) -> str:
    """Remove string literals and numbers so they aren't mistaken for identifiers."""
    sql = re.sub(r"'[^']*'", "''", sql)          # string literals → empty ''
    sql = re.sub(r'"[^"]*"', '""', sql)           # double-quoted → empty ""
    sql = re.sub(r'\b\d+(\.\d+)?\b', '0', sql)   # numbers → 0 (not an identifier)
    return sql


# ── NLP helpers for schema token filtering ────────────────────────────────────

_schema_nlp = None
_schema_nlp_tried = False


def _load_schema_nlp():
    global _schema_nlp, _schema_nlp_tried
    if _schema_nlp_tried:
        return _schema_nlp
    _schema_nlp_tried = True
    try:
        import spacy
        _schema_nlp = spacy.load("en_core_web_sm")
    except Exception:
        pass
    return _schema_nlp


def _looks_like_verb(word: str) -> bool:
    """Fallback heuristic when spaCy is unavailable."""
    return bool(re.search(r'(ed|ing|ize|ise|ate|ify|fy|en)$', word, re.IGNORECASE))


def _is_genuine_unknown(tok: str, known: set[str]) -> bool:
    """
    Return True only if tok is a real schema violation.

    Applies lemmatization + POS tagging (spaCy) to each underscore-split part:
    - Parts that lemmatise to a known column are not violations.
    - Parts whose POS is VERB/AUX are natural-language verbs, not column names
      (e.g. 'generated' in 'profit_generated').
    Only flag the token when at least one part remains that is neither a known
    column (or its lemma) nor a verb form.
    """
    nlp = _load_schema_nlp()
    parts = tok.split('_') if '_' in tok else [tok]

    noun_unknowns = []
    for part in parts:
        if part in known:
            continue
        if nlp:
            doc = nlp(part)
            t = doc[0] if len(doc) > 0 else None
            if t is not None:
                if t.lemma_ in known:        # e.g. "profits" → lemma "profit"
                    continue
                if t.pos_ in ('VERB', 'AUX'):  # e.g. "generated", "computed"
                    continue
        else:
            if _looks_like_verb(part):
                continue
        noun_unknowns.append(part)

    return len(noun_unknowns) > 0


# ── 1. Schema validation ──────────────────────────────────────────────────────

def validate_schema(
    sql: str,
    table_name: str,
    columns: list[str],
    question: str = "",
    session_id: str = "",
    user_id: str = "",
    extra_columns: Optional[list[str]] = None,
) -> tuple[bool, str]:
    """
    Check that the SQL only references columns that exist in the table schema.

    Parameters
    ----------
    extra_columns : additional columns from JOIN tables — these are valid and
                    should not be flagged as hallucinations.

    Returns (is_valid, error_hint).
    """
    if not columns:
        return True, ""   # can't validate without schema info

    known = {c.lower() for c in columns}
    if extra_columns:
        known |= {c.lower() for c in extra_columns}

    # All table-name parts are valid identifiers (catalog, schema, table)
    all_table_parts: set[str] = set()
    for tname in ([table_name] + list(re.split(r'[,\s]+', table_name))):
        for p in re.split(r'[.\s]', tname):
            if p:
                all_table_parts.add(p.lower())

    clean = _strip_literals(sql)

    # ── Collect SELECT aliases so they are not flagged in ORDER BY / HAVING ──
    # e.g. SELECT SUM(Units_Sold) AS total_units_sold … ORDER BY total_units_sold
    # The alias is valid in ORDER BY even though it's not a column name.
    select_aliases: set[str] = set()
    for alias in re.findall(
        r'\bAS\s+([a-zA-Z_][a-zA-Z0-9_]*)\b', clean, re.IGNORECASE
    ):
        select_aliases.add(alias.lower())

    # ── Also allow table-qualified references: t.col or alias.col ────────────
    # Strip table-qualifier prefixes so "s.Units_Sold" → check "units_sold" only
    clean_no_qual = re.sub(r'\b[a-zA-Z_]\w*\.(?=[a-zA-Z_])', '', clean)

    clause_patterns = [
        r'\bSELECT\b(.*?)\bFROM\b',
        r'\bWHERE\b(.*?)(?:\bGROUP\b|\bORDER\b|\bHAVING\b|\bLIMIT\b|$)',
        r'\bGROUP\s+BY\b(.*?)(?:\bHAVING\b|\bORDER\b|\bLIMIT\b|$)',
        r'\bORDER\s+BY\b(.*?)(?:\bLIMIT\b|$)',
        r'\bHAVING\b(.*?)(?:\bORDER\b|\bLIMIT\b|$)',
        r'\bON\b(.*?)(?:\bWHERE\b|\bGROUP\b|\bORDER\b|\bJOIN\b|$)',
    ]

    candidate_tokens: set[str] = set()
    for pat in clause_patterns:
        for segment in re.findall(pat, clean_no_qual, re.IGNORECASE | re.DOTALL):
            # Strip AS aliases before extracting tokens
            segment = re.sub(r'\bAS\s+[a-zA-Z_][a-zA-Z0-9_]*', '', segment, flags=re.IGNORECASE)
            for tok in re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', segment):
                candidate_tokens.add(tok.lower())

    unknown = [
        tok for tok in candidate_tokens
        if len(tok) > 1
        and tok not in _SQL_KEYWORDS
        and tok not in all_table_parts
        and tok not in known
        and tok not in select_aliases          # ← aliases reused in ORDER BY / HAVING
        and _is_genuine_unknown(tok, known)
    ]

    if unknown:
        hint = (
            f"Schema hallucination detected: the following identifiers do not exist "
            f"as columns in '{table_name}': {unknown}. "
            f"The valid columns are: {', '.join(columns)}. "
            f"Rewrite the SQL using ONLY these exact column names."
        )
        _trace("schema", question, sql, str(unknown), session_id, user_id)
        return False, hint

    return True, ""


# ── 2. Column-semantic validation (embedding-based, no LLM call) ──────────────

# Question words that are never metric/dimension terms
_METRIC_STOPWORDS = {
    "what", "is", "are", "the", "show", "give", "find", "get", "me",
    "calculate", "compute", "tell", "list", "display", "return", "fetch",
    "how", "many", "much", "for", "of", "in", "by", "per", "each", "all",
    "a", "an", "to", "from", "with", "and", "or", "not", "where", "when",
    "which", "who", "that", "this", "these", "those", "between", "above",
    "below", "than", "more", "less", "top", "bottom", "please", "can", "you",
    "do", "does", "did", "was", "were", "has", "have", "had", "will", "would",
    "could", "should", "my", "our", "their", "its", "am", "be", "been",
}

# Similarity thresholds
_SEMANTIC_MATCH_THRESHOLD  = 0.72   # question term → best schema column
_SEMANTIC_USAGE_THRESHOLD  = 0.55   # question term → column actually used in SQL
_SEMANTIC_MISMATCH_GAP     = 0.20   # best_col_sim - used_col_sim must exceed this to flag


def _extract_metric_terms(question: str) -> list[str]:
    """
    Pull candidate metric/dimension words from the question.

    e.g. "what is the total profit of LOCTITE 243 by region"
         → ["total", "profit", "loctite", "region"]  (stopwords removed)
    """
    words = re.findall(r'\b[a-zA-Z][a-zA-Z0-9_]*\b', question.lower())
    return [w for w in words if w not in _METRIC_STOPWORDS and len(w) > 2]


def _extract_select_col_refs(sql: str) -> list[str]:
    """
    Return lowercased identifiers referenced in the SELECT clause
    (after stripping AS aliases and SQL keywords).
    """
    m = re.search(r'\bSELECT\b(.*?)\bFROM\b', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return []
    clause = re.sub(r'\bAS\s+\w+', '', m.group(1), flags=re.IGNORECASE)
    tokens = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', clause)
    return [t.lower() for t in tokens if t.lower() not in _SQL_KEYWORDS]


# Lazy module-level embedding model (shared with other callers in this process)
_sem_model = None
_sem_model_lock = __import__("threading").Lock()


def _get_sem_model():
    global _sem_model
    if _sem_model is None:
        with _sem_model_lock:
            if _sem_model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                    _sem_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
                except Exception:
                    pass
    return _sem_model


def validate_column_semantics(
    question: str,
    sql: str,
    columns: list[str],
    table_name: str,
    session_id: str = "",
    user_id: str = "",
) -> tuple[bool, str]:
    """
    Embedding-based post-generation sanity check.

    For each key term extracted from the question, find the most semantically
    similar column in the schema.  Then check whether the SQL SELECT clause
    actually references that column.  If there is a high-confidence mismatch
    (e.g. question says "profit" → best column is "Profit", but SQL uses
    "Price"), return an actionable correction hint.

    Returns (is_valid, error_hint).
    No-op (returns True) when embeddings are unavailable.
    """
    if not columns:
        return True, ""

    model = _get_sem_model()
    if model is None:
        return True, ""   # embeddings unavailable — skip silently

    try:
        import numpy as np

        col_lower   = [c.lower() for c in columns]
        col_embs    = model.encode(col_lower, normalize_embeddings=True, show_progress_bar=False)

        metric_terms = _extract_metric_terms(question)
        if not metric_terms:
            return True, ""

        term_embs = model.encode(metric_terms, normalize_embeddings=True, show_progress_bar=False)

        used_refs  = set(_extract_select_col_refs(sql))

        hints: list[str] = []

        for term, t_emb in zip(metric_terms, term_embs):
            sims = np.dot(col_embs, t_emb)           # cosine sim to each column
            best_idx  = int(np.argmax(sims))
            best_sim  = float(sims[best_idx])
            best_col  = col_lower[best_idx]

            # Only act when we have a confident best column for this term
            if best_sim < _SEMANTIC_MATCH_THRESHOLD:
                continue

            # Check if any used ref is close enough to the best column
            if best_col in used_refs:
                continue   # exact match — all good

            # Find the highest sim of the actually-used columns to this term
            used_sims = [float(sims[col_lower.index(r)]) for r in used_refs if r in col_lower]
            top_used_sim = max(used_sims) if used_sims else 0.0

            # Flag only when the gap is significant enough to be a real mismatch
            if best_sim - top_used_sim >= _SEMANTIC_MISMATCH_GAP:
                canonical_col = columns[best_idx]   # original casing
                hints.append(
                    f"The question asks for '{term}' which maps to column "
                    f"'{canonical_col}' (similarity {best_sim:.2f}), but the SQL "
                    f"does not use it. Use '{canonical_col}' directly instead of "
                    f"computing it from other columns."
                )
                _trace("semantic_mismatch", question, sql,
                       f"term='{term}' best_col='{canonical_col}' top_used_sim={top_used_sim:.2f}",
                       session_id, user_id)

        if hints:
            hint = (
                "Column semantic mismatch detected:\n" + "\n".join(f"- {h}" for h in hints) +
                f"\nValid columns: {', '.join(columns)}. Rewrite the SQL using the correct columns."
            )
            return False, hint

        return True, ""

    except Exception:
        return True, ""   # never block on unexpected errors


# ── 3. Logical validation ─────────────────────────────────────────────────────

_LOGICAL_PROMPT = """\
You are a SQL review assistant. Given a user question and a generated SQL query, \
determine whether the SQL LOGICALLY and CORRECTLY answers the question.

Focus on:
- Does the SQL retrieve the right columns for the question?
- Are aggregations (SUM, COUNT, AVG) used correctly with GROUP BY when needed?
- Are WHERE/HAVING filters appropriate to the question?
- Would the SQL return data the user actually wants?

User question: {question}
Table: {table_name}
Available columns: {columns}
Generated SQL: {sql}

Reply ONLY with a JSON object (no markdown):
{{"valid": true/false, "issue": "one-sentence description of the problem or empty string if valid", "fixed_sql": "corrected SQL or empty string if valid"}}
"""


def validate_logic(
    question: str,
    sql: str,
    table_name: str,
    columns: list[str],
    llm_model: str = "gemini-2.5-flash",
    session_id: str = "",
    user_id: str = "",
) -> tuple[bool, str]:
    """
    Ask the LLM to judge whether the SQL logically answers the question.
    Only run on the first attempt to avoid cascading LLM cost.

    Returns (is_valid, error_hint_or_fixed_sql).
    """
    try:
        from .llm_registry import get_llm
        import re as _re

        prompt = _LOGICAL_PROMPT.format(
            question=question,
            table_name=table_name,
            columns=", ".join(columns or []),
            sql=sql,
        )
        llm = get_llm(llm_model)
        response = llm.invoke(prompt).content.strip()

        # Strip markdown fences
        response = _re.sub(r"```(?:json)?\s*|\s*```", "", response).strip()
        # Extract JSON object
        m = _re.search(r"\{.*\}", response, _re.DOTALL)
        if not m:
            return True, ""   # can't parse → don't block

        parsed = json.loads(m.group())
        if parsed.get("valid", True):
            return True, ""

        issue = parsed.get("issue", "")
        fixed = parsed.get("fixed_sql", "").strip()

        hint = f"Logical hallucination detected: {issue}. "
        if fixed:
            hint += f"Suggested correction: {fixed}"

        _trace("logical", question, sql, issue, session_id, user_id)
        return False, hint

    except Exception:
        return True, ""   # validation failure → don't block execution


# ── 3. Empty-result diagnosis ─────────────────────────────────────────────────

def diagnose_empty_result(
    sql: str,
    table_name: str,
    data_service: "DatabricksService",
    question: str = "",
    session_id: str = "",
    user_id: str = "",
) -> str:
    """
    When a query returns 0 rows, run diagnostic queries to understand why and
    return a re-prompting hint.

    Diagnostics:
    1. COUNT(*) on the table — confirm data exists at all.
    2. Sample values for filter columns used in WHERE clause.
    """
    try:
        def _run(q: str) -> list[dict]:
            return data_service.execute_query(q, timeout_seconds=15)

        # 1. Does the table have rows at all?
        count_sql = f"SELECT COUNT(*) AS total_rows FROM {table_name}"
        count_rows = _run(count_sql)
        total = (count_rows[0].get("total_rows") or count_rows[0].get("TOTAL_ROWS") or 0) if count_rows else 0

        if total == 0:
            hint = (
                f"Empty-result: table '{table_name}' contains 0 rows — "
                f"no data is available to answer this question."
            )
            _trace("empty_result", question, sql, "table is empty", session_id, user_id)
            return hint

        # 2. Extract WHERE filter columns and sample their actual values
        clean = _strip_literals(sql)
        where_m = re.search(
            r'\bWHERE\b(.*?)(?:\bGROUP\b|\bORDER\b|\bHAVING\b|\bLIMIT\b|$)',
            clean, re.IGNORECASE | re.DOTALL
        )

        sampled: list[str] = []
        if where_m:
            where_clause = where_m.group(1)
            # Identify left-hand side column names: col = _, col LIKE _, etc.
            filter_cols = re.findall(
                r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=|!=|<>|LIKE|IN|>|<|>=|<=)',
                where_clause, re.IGNORECASE
            )
            filter_cols = [c for c in filter_cols if c.lower() not in _SQL_KEYWORDS]

            for col in filter_cols[:2]:   # limit to 2 columns to keep it cheap
                try:
                    sample_sql = f"SELECT DISTINCT {col} FROM {table_name} ORDER BY {col} LIMIT 5"
                    rows = _run(sample_sql)
                    vals = [str(list(r.values())[0]) for r in rows if r]
                    if vals:
                        sampled.append(f"{col}: {', '.join(vals)}")
                except Exception:
                    pass

        # Build a user-friendly "no data found" message
        hint_parts = [
            f"No results were found in **{table_name.split('.')[-1]}**."
        ]
        if sampled:
            hint_parts.append(
                f"The filter condition did not match any rows. "
                f"Here are some example values that exist in the filtered column(s) — {'; '.join(sampled)}. "
                f"Try using one of these values or broaden the filter."
            )
        else:
            hint_parts.append(
                f"The filter condition did not match any of the {total:,} rows in the table. "
                "Try broadening the filter or removing it."
            )

        hint = " ".join(hint_parts)
        _trace("empty_result", question, sql, hint, session_id, user_id)
        return hint

    except Exception as exc:
        return f"No results were found. ({exc})"


# ── 4. Feedback storage ───────────────────────────────────────────────────────

_FEEDBACK_FILE = _ROOT / "eval" / "user_feedback.jsonl"


def store_feedback(
    message_id: str,
    question: str,
    sql: Optional[str],
    final_answer: Optional[str],
    rating: str,                        # "good" | "bad"
    comment: str = "",
    session_id: str = "",
    user_id: str = "",
    route: str = "",                    # "sql" | "rag" | "both" | "schema"
    history: Optional[list] = None,     # last N conversation turns at time of rating
) -> None:
    """
    Append a user feedback record to eval/user_feedback.jsonl.

    Stores both the immediate question/answer AND the conversation history
    snapshot so that analysts can reconstruct the full context when
    investigating bad ratings — especially multi-turn misunderstandings.

    Feedback vs. multi-turn conversation
    -------------------------------------
    history   — the running conversation context sent to the LLM on every
                 query turn; it is ephemeral and lives in the frontend.
    feedback  — a permanent, immutable rating of one specific answer;
                 the history snapshot here is a frozen copy at rating time,
                 not the live conversation state.
    """
    try:
        _FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp":    datetime.utcnow().isoformat(),
            "message_id":   message_id,
            "session_id":   session_id,
            "user_id":      user_id,
            "route":        route,
            "question":     question,
            "history_snapshot": (history or [])[-6:],  # last 3 turns (user+assistant pairs)
            "sql":          sql,
            "final_answer": final_answer,
            "rating":       rating,
            "comment":      comment,
        }
        with open(_FEEDBACK_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


# ── 5. Value-existence validation (uses ValueIndex) ───────────────────────────

def _extract_where_literals(sql: str) -> list[str]:
    """Extract single-quoted string literals from the SQL WHERE clause."""
    where_m = re.search(
        r'\bWHERE\b(.*?)(?:\bGROUP\b|\bORDER\b|\bHAVING\b|\bLIMIT\b|$)',
        sql, re.IGNORECASE | re.DOTALL,
    )
    if not where_m:
        return []
    return re.findall(r"'([^']+)'", where_m.group(1))


def _format_not_found_message(candidate: str, result, table_name: str) -> str:
    """Build a user-friendly 'not found' message with suggestions."""
    suggestions = [m["value"] for m in result.top_matches if m["confidence"] >= 0.45][:3]
    col_hint    = result.top_matches[0]["col"] if result.top_matches else ""
    table_simple = table_name.split(".")[-1] if table_name else "the table"

    msg = f"**'{candidate}'** was not found in {table_simple}"
    if col_hint:
        msg += f" (column: `{col_hint}`)"
    if suggestions:
        quoted = ", ".join(f"'{s}'" for s in suggestions)
        msg += f". Did you mean: {quoted}?"
    else:
        msg += ". Please check the spelling or try a different value."
    return msg


def validate_query_values(
    question: str,
    value_index: "InvertedIndex",
    table_name: str = "",
    session_id: str = "",
    user_id: str = "",
) -> tuple[bool, str]:
    """
    Pre-SQL check: extract named entities / quoted strings from the user's
    question and verify each against the value index.

    Only blocks on high-priority candidates (PERSON, ORG, GPE, quoted) that
    score below FOUND_THRESHOLD.

    Returns (is_valid, user_facing_message).
    """
    try:
        from ..query_value_extractor import extract_filter_candidates
    except ImportError:
        from query_value_extractor import extract_filter_candidates

    if not value_index or not value_index.is_ready():
        return True, ""   # index not ready — skip, don't block

    HIGH_PRIORITY = {"PERSON", "ORG", "GPE"}
    # Pattern for values that are purely numeric/date/time — skip index check
    _NUMERIC_RE  = re.compile(r'^[\d\s\-/:.,]+$')
    # For non-PERSON entities (ORG/GPE), require a digit to avoid false rejections
    # on brand-only names like "Loctite" that appear as LIKE patterns in SQL.
    # PERSON names (e.g. "Emma Liu") never have digits but must still be checked.
    _HAS_DIGIT_RE = re.compile(r'\d')

    candidates = extract_filter_candidates(question)
    high = [
        c for c in candidates
        if (c["entity_type"] in HIGH_PRIORITY or c["method"] == "quoted")
        and not _NUMERIC_RE.match(c["text"])        # skip dates, numbers, timestamps
        and (
            c["entity_type"] == "PERSON"            # always check person names
            or c["method"] == "quoted"              # always check explicitly quoted values
            or _HAS_DIGIT_RE.search(c["text"])      # ORG/GPE: require a digit (skip brand-only)
        )
    ]
    if not high:
        return True, ""

    not_found_msgs = []
    for cand in high:
        result = value_index.search_value(cand["text"], table=table_name or None)
        if not result.found:
            not_found_msgs.append(_format_not_found_message(cand["text"], result, table_name))
            _trace("value_not_found_pre", question, "", cand["text"], session_id, user_id)

    if not_found_msgs:
        return False, "\n".join(not_found_msgs)
    return True, ""


def validate_sql_values(
    sql: str,
    table_name: str,
    value_index: "InvertedIndex",
    question: str = "",
    session_id: str = "",
    user_id: str = "",
) -> tuple[bool, str]:
    """
    Post-SQL check: extract string literals from the SQL WHERE clause and
    verify each against the value index.

    More precise than validate_query_values because the literals come
    directly from the generated SQL, not from noisy natural language.

    Returns (is_valid, user_facing_message).
    """
    if not value_index or not value_index.is_ready():
        return True, ""

    literals = _extract_where_literals(sql)
    if not literals:
        return True, ""

    _NUMERIC_RE  = re.compile(r'^[\d\s\-/:.,]+$')
    _WILDCARD_RE = re.compile(r'[%_]')   # SQL LIKE wildcards — not exact values
    not_found_msgs = []
    for literal in literals:
        if len(literal) < 2:
            continue
        if _NUMERIC_RE.match(literal):      # skip dates, numbers, timestamps
            continue
        if _WILDCARD_RE.search(literal):    # skip LIKE patterns e.g. 'Loctite%'
            continue
        result = value_index.search_value(literal, table=table_name or None)
        if not result.found:
            not_found_msgs.append(_format_not_found_message(literal, result, table_name))
            _trace("value_not_found_post", question, sql, literal, session_id, user_id)

    if not_found_msgs:
        return False, "\n".join(not_found_msgs)
    return True, ""
