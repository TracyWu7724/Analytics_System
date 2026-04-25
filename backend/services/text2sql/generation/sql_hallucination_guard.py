"""
sql_hallucination_guard.py — Self-correction layer for Text2SQL hallucinations.

Covers four hallucination types:
  1. Schema       — LLM uses columns/tables that don't exist in the schema
  2. Logical      — SQL is syntactically valid but semantically wrong
  3. Execution    — SQL fails at runtime (handled upstream by retry loop)
  4. Empty result — Query returns 0 rows when data should exist

Each check returns a (passed: bool, error_hint: str) tuple.
The error_hint is injected into the next generation attempt.

Traces are written to eval/hallucination_traces.jsonl for analysis.
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
_TRACE_FILE = _ROOT / "eval" / "hallucination_traces.jsonl"
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
) -> tuple[bool, str]:
    """
    Check that the SQL only references columns that exist in the table schema.

    Strategy: extract identifiers from the SELECT clause, WHERE clause,
    GROUP BY, ORDER BY, and JOIN ON conditions, then check each against the
    known columns list. SQL keywords and the table name are excluded.

    Returns (is_valid, error_hint).
    """
    if not columns:
        return True, ""   # can't validate without schema info

    known = {c.lower() for c in columns}
    tname_parts = {p.lower() for p in re.split(r'[.\s]', table_name) if p}

    clean = _strip_literals(sql)

    # Extract identifiers only from column-bearing clauses
    # SELECT … FROM, WHERE, GROUP BY, ORDER BY, HAVING, ON
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
        for segment in re.findall(pat, clean, re.IGNORECASE | re.DOTALL):
            for tok in re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', segment):
                candidate_tokens.add(tok.lower())

    unknown = [
        tok for tok in candidate_tokens
        if len(tok) > 1                          # skip single-char noise (_, t, n …)
        and tok not in _SQL_KEYWORDS
        and tok not in tname_parts
        and tok not in known
        and _is_genuine_unknown(tok, known)      # skip verb forms / column+verb compounds
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


# ── 2. Logical validation ─────────────────────────────────────────────────────

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
                f"The value you searched for does not exist in the database. "
                f"Here are some example values that do exist — {'; '.join(sampled)}."
            )
        else:
            hint_parts.append(
                f"The filter condition did not match any of the {total:,} rows in the table. "
                "Check that the name or value is spelled correctly."
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
    rating: str,          # "good" | "bad"
    comment: str = "",
    session_id: str = "",
    user_id: str = "",
) -> None:
    """Append a user feedback record to eval/user_feedback.jsonl."""
    try:
        _FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "message_id": message_id,
            "session_id": session_id,
            "user_id": user_id,
            "question": question,
            "sql": sql,
            "final_answer": final_answer,
            "rating": rating,
            "comment": comment,
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
    _NUMERIC_RE = re.compile(r'^[\d\s\-/:.,]+$')

    candidates = extract_filter_candidates(question)
    high = [
        c for c in candidates
        if (c["entity_type"] in HIGH_PRIORITY or c["method"] == "quoted")
        and not _NUMERIC_RE.match(c["text"])   # skip dates, numbers, timestamps
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

    _NUMERIC_RE = re.compile(r'^[\d\s\-/:.,]+$')
    not_found_msgs = []
    for literal in literals:
        if len(literal) < 2:
            continue
        if _NUMERIC_RE.match(literal):   # skip dates, numbers, timestamps
            continue
        result = value_index.search_value(literal, table=table_name or None)
        if not result.found:
            not_found_msgs.append(_format_not_found_message(literal, result, table_name))
            _trace("value_not_found_post", question, sql, literal, session_id, user_id)

    if not_found_msgs:
        return False, "\n".join(not_found_msgs)
    return True, ""
