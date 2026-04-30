#!/bin/bash
set -e

# ── Optional: sync inverted index from S3 ────────────────────────────────────
# Set INDEX_S3_URI=s3://your-bucket/index/ to load a pre-built index instead
# of rebuilding from Databricks on every cold start.
if [ -n "$INDEX_S3_URI" ]; then
    echo "[entrypoint] Syncing index from ${INDEX_S3_URI} → ${INDEX_DIR}"
    aws s3 sync "$INDEX_S3_URI" "$INDEX_DIR" --quiet
    echo "[entrypoint] Index sync complete"
fi

# ── Optional: sync RAG embeddings from S3 ────────────────────────────────────
# Set RAG_EMBED_S3_URI=s3://your-bucket/rag/embedding/ to load FAISS indexes.
if [ -n "$RAG_EMBED_S3_URI" ] && [ -n "$RAG_EMBED_DIR" ]; then
    echo "[entrypoint] Syncing RAG embeddings from ${RAG_EMBED_S3_URI} → ${RAG_EMBED_DIR}"
    aws s3 sync "$RAG_EMBED_S3_URI" "$RAG_EMBED_DIR" --quiet
    echo "[entrypoint] Embeddings sync complete"
fi

# ── Start FastAPI ─────────────────────────────────────────────────────────────
exec uvicorn backend.services.api.agent:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${UVICORN_WORKERS:-1}"
