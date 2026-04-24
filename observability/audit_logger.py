"""
audit_logger.py — Structured audit logging for the RAG and Text-to-SQL pipelines.

Writes one JSON line per event to a rotating log file so that every query,
upload, deletion, and error has a tamper-evident, searchable record.

Usage
-----
    from observability.audit_logger import audit

    audit.query("show top 10 sales", table="gold.sales", model="gemini-2.5-flash")
    audit.upload("sales.csv", table_name="uploaded_sales", row_count=500)
    audit.error("query", error="timeout", question="show everything")
    audit.rag_query("What is cure time?", product="LOCTITE 454", model="gemini-2.5-flash")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Internal logger setup
# ---------------------------------------------------------------------------

def _build_logger(log_dir: Optional[str] = None) -> logging.Logger:
    logger = logging.getLogger("decision_system.audit")
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.INFO)
    logger.propagate = False

    if log_dir is None:
        log_dir = os.environ.get(
            "AUDIT_LOG_DIR",
            os.path.join(os.path.dirname(__file__), "..", "logs"),
        )
    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, "audit.log")
    handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB per file
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


_logger = _build_logger()


# ---------------------------------------------------------------------------
# Core write helper
# ---------------------------------------------------------------------------

def _write(event_type: str, **fields: Any) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        **{k: v for k, v in fields.items() if v is not None},
    }
    _logger.info(json.dumps(record, default=str))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class AuditLogger:
    """Thin façade around _write() with named methods for each event type."""

    # -- Text-to-SQL ----------------------------------------------------------

    def query(
        self,
        question: str,
        *,
        table: Optional[str] = None,
        sql: Optional[str] = None,
        model: Optional[str] = None,
        row_count: Optional[int] = None,
        duration_ms: Optional[float] = None,
        trace_url: Optional[str] = None,
        user: Optional[str] = None,
    ) -> None:
        """Log a natural-language → SQL query execution."""
        _write(
            "text2sql.query",
            question=question,
            table=table,
            sql=sql,
            model=model,
            row_count=row_count,
            duration_ms=duration_ms,
            trace_url=trace_url,
            user=user,
        )

    def upload(
        self,
        filename: str,
        *,
        table_name: Optional[str] = None,
        row_count: Optional[int] = None,
        column_count: Optional[int] = None,
        user: Optional[str] = None,
    ) -> None:
        """Log a file upload event."""
        _write(
            "text2sql.upload",
            filename=filename,
            table_name=table_name,
            row_count=row_count,
            column_count=column_count,
            user=user,
        )

    def delete_table(
        self,
        table_name: str,
        *,
        user: Optional[str] = None,
    ) -> None:
        """Log an uploaded-table deletion."""
        _write("text2sql.delete_table", table_name=table_name, user=user)

    # -- RAG ------------------------------------------------------------------

    def rag_query(
        self,
        question: str,
        *,
        product: Optional[str] = None,
        model: Optional[str] = None,
        embed_model: Optional[str] = None,
        chunks_retrieved: Optional[int] = None,
        duration_ms: Optional[float] = None,
        trace_url: Optional[str] = None,
        user: Optional[str] = None,
    ) -> None:
        """Log a RAG query event."""
        _write(
            "rag.query",
            question=question,
            product=product,
            model=model,
            embed_model=embed_model,
            chunks_retrieved=chunks_retrieved,
            duration_ms=duration_ms,
            trace_url=trace_url,
            user=user,
        )

    def rag_index(
        self,
        pdf_count: int,
        *,
        chunk_count: Optional[int] = None,
        embed_model: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> None:
        """Log a RAG indexing run."""
        _write(
            "rag.index",
            pdf_count=pdf_count,
            chunk_count=chunk_count,
            embed_model=embed_model,
            duration_ms=duration_ms,
        )

    # -- Errors ---------------------------------------------------------------

    def error(
        self,
        pipeline: str,
        *,
        error: str,
        question: Optional[str] = None,
        table: Optional[str] = None,
        user: Optional[str] = None,
    ) -> None:
        """Log an error in any pipeline."""
        _write(
            f"{pipeline}.error",
            error=error,
            question=question,
            table=table,
            user=user,
        )


# Singleton instance — import and use directly:
#   from observability.audit_logger import audit
audit = AuditLogger()
