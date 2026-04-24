"""Persist question/SQL pairs to the local query history store.

Mirrors the role of WrenAI's HistoricalQuestion pipeline but without vector
embeddings — retrieval is fuzzy-match based, so indexing is just a clean write
to the SQLite ``recent_queries`` table managed by DatabricksService.

Responsibilities
----------------
* Deduplicate: skip questions that are exact matches already in recent history.
* Prune: keep the table from growing unboundedly (cap at ``max_history``).
* (Optional) schema upgrade: add a ``sql`` column so SQL can be stored
  alongside each question for richer retrieval context in the future.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

_DEFAULT_MAX_HISTORY = 200
_DEDUP_WINDOW = 20  # how many recent rows to check for exact duplicates


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def ensure_sql_column(db_path: str) -> None:
    """Add a ``sql`` column to ``recent_queries`` if it does not exist yet.

    Safe to call on every startup — it is a no-op when the column is already
    present.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(recent_queries)")
        columns = {row[1] for row in cursor.fetchall()}
        if "sql" not in columns:
            cursor.execute("ALTER TABLE recent_queries ADD COLUMN sql TEXT")
            conn.commit()
            logger.info("Added 'sql' column to recent_queries table.")
        conn.close()
    except Exception as exc:
        logger.warning(f"Could not ensure sql column: {exc}")


# ---------------------------------------------------------------------------
# Core indexing functions
# ---------------------------------------------------------------------------

def index_question(
    question: str,
    data_service,
    sql: str | None = None,
    max_history: int = _DEFAULT_MAX_HISTORY,
) -> bool:
    """Save a question (and optionally its generated SQL) to query history.

    Args:
        question:    The user's natural-language question.
        data_service: ``DatabricksService`` instance that owns the SQLite DB.
        sql:         Generated SQL to store alongside the question.
                     Requires :func:`ensure_sql_column` to have been called first.
        max_history: Hard cap on total rows kept in ``recent_queries``.

    Returns:
        ``True`` if the entry was written, ``False`` if it was skipped (duplicate)
        or if an error occurred.
    """
    question = question.strip()
    if not question:
        return False

    try:
        conn = sqlite3.connect(data_service.local_db_path)
        cursor = conn.cursor()

        # Dedup: skip if this exact question already appears in the recent window
        cursor.execute(
            "SELECT 1 FROM recent_queries ORDER BY created_at DESC LIMIT ?",
            (_DEDUP_WINDOW,),
        )
        # Rebuild with actual text for the check
        cursor.execute(
            """
            SELECT query_text FROM recent_queries
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (_DEDUP_WINDOW,),
        )
        recent_texts = {row[0] for row in cursor.fetchall()}
        if question in recent_texts:
            logger.debug(f"Skipping duplicate question: {question[:60]!r}")
            conn.close()
            return False

        # Write — try with sql column, fall back to text-only
        try:
            cursor.execute(
                "INSERT INTO recent_queries (query_text, sql, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (question, sql),
            )
        except sqlite3.OperationalError:
            # sql column does not exist yet — write text only
            cursor.execute(
                "INSERT INTO recent_queries (query_text, created_at) VALUES (?, CURRENT_TIMESTAMP)",
                (question,),
            )

        # Prune: delete oldest rows beyond the cap
        cursor.execute(
            """
            DELETE FROM recent_queries
            WHERE id NOT IN (
                SELECT id FROM recent_queries
                ORDER BY created_at DESC
                LIMIT ?
            )
            """,
            (max_history,),
        )

        conn.commit()
        conn.close()
        logger.info(f"Indexed question: {question[:60]!r}")
        return True

    except Exception as exc:
        logger.error(f"Failed to index question: {exc}")
        return False


def index_question_background(
    question: str,
    data_service,
    sql: str | None = None,
) -> None:
    """Fire-and-forget wrapper suitable for FastAPI ``BackgroundTasks``.

    Swallows all exceptions so a history write never crashes the request.
    """
    index_question(question, data_service, sql=sql)
