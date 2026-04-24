"""
api/agent.py — v2 FastAPI endpoint for the combined Text2SQL + RAG agent.

POST /agent/query
    Accepts a question and returns the agent's answer, routing decision,
    SQL query (if used), retrieved chunks (if used), and a LangSmith trace URL.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import threading
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

# ── LangSmith tracing (optional) ────────────────────────────────────────────
_LANGSMITH_ENABLED = bool(os.getenv("LANGCHAIN_API_KEY"))
_ls_client = None
_tl_run_id = threading.local()

try:
    from langsmith import Client, traceable
    from langsmith.run_helpers import get_current_run_tree
    if _LANGSMITH_ENABLED:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        _ls_client = Client()
except ImportError:
    _LANGSMITH_ENABLED = False


def _share_run(run_id: Optional[str]) -> Optional[str]:
    if not _ls_client or not run_id:
        return None
    try:
        _ls_client.flush()
    except Exception:
        pass
    import time
    for wait in [1, 2, 3]:
        time.sleep(wait)
        try:
            return _ls_client.share_run(run_id)
        except Exception:
            continue
    return None


# ── Service imports ──────────────────────────────────────────────────────────
try:
    from ..text2sql.db.databricks_service import DatabricksService
    from ..text2sql.db.upload_service import UploadService
    from ..agent.graph import build_agent
    from ..agent.tools.rag_tool import run_rag
    from ..text2sql.generation.llm_registry import list_llm_models
except ImportError:
    from db.databricks_service import DatabricksService
    from db.upload_service import UploadService
    from agent.graph import build_agent
    from agent.tools.rag_tool import run_rag
    from generation.llm_registry import list_llm_models

# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Decision Agent API",
    description="v2 agentic pipeline combining Text2SQL and RAG",
    version="2.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── RAG path helpers ─────────────────────────────────────────────────────────

def _model_to_file_key(model_name: str) -> str:
    """Convert HuggingFace model name to the file-system key used in embedding filenames.

    e.g. 'BAAI/bge-base-en-v1.5'                     → 'BAAI_bge-base-en-v1-5'
         'sentence-transformers/all-MiniLM-L6-v2'     → 'sentence-transformers_all-MiniLM-L6-v2'
    """
    return model_name.replace("/", "_").replace(".", "-")


def _resolve_rag_paths(embed_dir: str, model_name: str) -> tuple[str, str]:
    """Return (metadata_path, faiss_path) for a given embedding dir and model."""
    key = _model_to_file_key(model_name)
    meta = os.path.join(embed_dir, f"embeddings_{key}_meta_2.jsonl")
    faiss = os.path.join(embed_dir, f"embeddings_{key}_2.index")
    return meta, faiss


# ── Singletons ───────────────────────────────────────────────────────────────
_data_service = DatabricksService()
_data_service.init_local_db()
_upload_service = UploadService(_data_service)

_EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
_RERANKER_MODEL = os.getenv("RAG_RERANKER_MODEL", None)

_embed_dir = os.getenv("RAG_EMBED_DIR", "")
if _embed_dir:
    _RAG_METADATA_PATH, _RAG_FAISS_PATH = _resolve_rag_paths(_embed_dir, _EMBED_MODEL)
else:
    # Allow explicit overrides if RAG_EMBED_DIR is not set
    _RAG_METADATA_PATH = os.getenv("RAG_METADATA_PATH", "")
    _RAG_FAISS_PATH = os.getenv("RAG_FAISS_PATH", "")

_rag_configured = bool(_RAG_METADATA_PATH and os.path.exists(_RAG_METADATA_PATH))
if _rag_configured:
    print(f"RAG configured: model={_EMBED_MODEL}")
    print(f"  metadata : {_RAG_METADATA_PATH}")
    print(f"  faiss    : {_RAG_FAISS_PATH}")
else:
    print("RAG not configured — agent will SQL-only until RAG_EMBED_DIR is set")

# Build the compiled LangGraph agent once at startup
_agent = build_agent(
    data_service=_data_service,
    metadata_path=_RAG_METADATA_PATH,
    faiss_path=_RAG_FAISS_PATH,
    embed_model_name=_EMBED_MODEL,
    reranker_model_name=_RERANKER_MODEL,
)


# ── Request / Response models ─────────────────────────────────────────────────
class AgentQueryRequest(BaseModel):
    question: str
    llm_model: str = "gemini-2.5-flash"
    uploaded_table: Optional[str] = None
    history: list[dict] = []


class RagQueryRequest(BaseModel):
    question: str
    llm_model: str = "gemini-2.5-flash"
    history: list[dict] = []


class RagQueryResponse(BaseModel):
    question: str
    answer: Optional[str]
    sources: Optional[list[str]] = None
    chunks: Optional[list[dict]] = None
    error: Optional[str] = None
    trace_url: Optional[str] = None


class AgentQueryResponse(BaseModel):
    question: str
    route: Optional[str]
    route_reasoning: Optional[str]
    final_answer: Optional[str]
    sql_query: Optional[str] = None
    sql_rows: Optional[list[dict]] = None
    sql_table: Optional[str] = None
    sql_attempts: int = 0
    rag_chunks: Optional[list[dict]] = None
    error: Optional[str] = None
    trace_url: Optional[str] = None


# ── Traced agent runner ───────────────────────────────────────────────────────
if _LANGSMITH_ENABLED:
    @traceable(run_type="chain", name="agent-query")
    def _run_agent(initial_state: dict) -> dict:
        rt = get_current_run_tree()
        _tl_run_id.value = str(rt.id) if rt else None
        return _agent.invoke(initial_state)
else:
    def _run_agent(initial_state: dict) -> dict:
        _tl_run_id.value = None
        return _agent.invoke(initial_state)


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    """Return a signed token for the given credentials."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "../../../.."))
        from auth.permission_auth import login_for_token
        token = login_for_token(username, password)
        return {"access_token": token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Auth error: {e}")


@app.get("/")
async def root():
    return {
        "message": "Decision Agent API v2",
        "status": "running",
        "endpoints": {
            "POST /agent/query": "Run the combined Text2SQL + RAG agent",
            "GET /agent/health": "Health check",
        },
    }


@app.get("/llm-models")
async def get_llm_models():
    return list_llm_models()


@app.get("/agent/health")
async def health():
    return {
        "status": "ok",
        "rag_configured": _rag_configured,
        "embed_model": _EMBED_MODEL if _rag_configured else None,
        "metadata_path": _RAG_METADATA_PATH if _rag_configured else None,
    }


def _get_optional_user():
    """Lazy import to avoid circular dependency at module load time."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "../../../.."))
        from auth.permission_auth import get_optional_user
        return get_optional_user
    except Exception:
        return lambda authorization=None: None


@app.post("/agent/query", response_model=AgentQueryResponse)
async def agent_query(request: AgentQueryRequest, authorization: Optional[str] = Header(default=None)):
    initial_state: dict = {
        "question": request.question,
        "history": request.history,
        "uploaded_table": request.uploaded_table,
        "llm_model": request.llm_model,
        "route": None,
        "route_reasoning": None,
        "sql_table": None,
        "sql_query": None,
        "sql_rows": None,
        "sql_error": None,
        "sql_attempts": 0,
        "rag_answer": None,
        "rag_chunks": None,
        "rag_error": None,
        "final_answer": None,
        "error": None,
        "denied_tables": [],
        "denied_rag_sources": [],
    }

    # Apply data-level access restrictions if the user is authenticated
    try:
        from auth.permission_auth import auth_service
        from fastapi import Request
        if authorization:
            token = authorization.replace("Bearer ", "").strip()
            user = auth_service.verify_token(token)
            if user:
                initial_state = user.adjust_agent_state(initial_state)
    except Exception:
        pass  # auth module unavailable — serve without restrictions

    try:
        # Run agent synchronously (LangGraph is sync); offload to thread so we
        # don't block the event loop
        _tl_run_id.value = None
        result = await asyncio.to_thread(_run_agent, initial_state)
        run_id = getattr(_tl_run_id, "value", None)
        trace_url = await asyncio.to_thread(_share_run, run_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    return AgentQueryResponse(
        question=request.question,
        route=result.get("route"),
        route_reasoning=result.get("route_reasoning"),
        final_answer=result.get("final_answer"),
        sql_query=result.get("sql_query"),
        sql_rows=result.get("sql_rows"),
        sql_table=result.get("sql_table"),
        sql_attempts=result.get("sql_attempts", 0),
        rag_chunks=result.get("rag_chunks"),
        error=result.get("error"),
        trace_url=trace_url,
    )


@app.post("/rag/query", response_model=RagQueryResponse)
async def rag_query(request: RagQueryRequest):
    if not _rag_configured:
        raise HTTPException(
            status_code=503,
            detail="RAG not configured. Set RAG_EMBED_DIR in .env and restart.",
        )

    def _run_rag() -> dict:
        return run_rag(
            question=request.question,
            metadata_path=_RAG_METADATA_PATH,
            faiss_path=_RAG_FAISS_PATH,
            embed_model_name=_EMBED_MODEL,
            llm_model=request.llm_model,
            history=request.history,
        )

    try:
        result = await asyncio.to_thread(_run_rag)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG error: {e}")

    sources = list({c["source"] for c in result.get("chunks", []) if c.get("source")})

    return RagQueryResponse(
        question=request.question,
        answer=result.get("answer"),
        sources=sources or None,
        chunks=result.get("chunks"),
        error=result.get("error"),
    )


# ── File upload ───────────────────────────────────────────────────────────────

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    if not any(file.filename.lower().endswith(ext) for ext in [".csv", ".xlsx", ".xls"]):
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        try:
            tmp.write(await file.read())
            tmp.flush()
            result = _upload_service.process_uploaded_file(tmp.name, file.filename)
            if not result["success"]:
                raise HTTPException(status_code=400, detail=f"File processing failed: {result['error']}")

            preview_data = _data_service.query_uploaded_table(
                f"SELECT * FROM {result['table_name']} LIMIT 10"
            )
            return {
                "success": True,
                "message": "File uploaded successfully",
                "table_name": result["table_name"],
                "row_count": result["row_count"],
                "column_count": result["column_count"],
                "columns": result["columns"],
                "preview_data": preview_data,
                "preview_count": len(preview_data),
                "original_filename": result.get("original_filename"),
                "file_extension": result.get("file_extension"),
            }
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


@app.get("/table/{table_name}/preview")
async def get_table_preview(table_name: str, limit: int = 5):
    try:
        if table_name.startswith("uploaded_"):
            conn = sqlite3.connect(_data_service.local_db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
                )
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = [col["name"] for col in cursor.fetchall()]
                cursor.execute(f"SELECT * FROM {table_name} LIMIT ?", (limit,))
                rows = [dict(row) for row in cursor.fetchall()]
                cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
                total_rows = cursor.fetchone()["count"]
            finally:
                conn.close()

            return {
                "table_name": table_name,
                "columns": columns,
                "rows": rows,
                "preview_count": len(rows),
                "total_rows": total_rows,
                **_data_service.get_table_metadata(table_name),
            }

        return _data_service.get_table_preview(table_name, limit)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching table preview: {e}")


# ── Diagnostics ──────────────────────────────────────────────────────────────

@app.get("/diagnostics")
async def diagnostics():
    """Return status of Databricks, LLM providers, and the RAG knowledge base."""
    import time as _time

    result: dict = {}

    # 1. Databricks connection
    def _check_databricks():
        t0 = _time.perf_counter()
        try:
            required = [
                _data_service.server_hostname,
                _data_service.client_id,
                _data_service.client_secret,
                _data_service.http_path,
            ]
            if not all(required):
                return {"status": "misconfigured", "message": "One or more DATABRICKS_* env vars not set", "latency_ms": 0}
            conn = _data_service.get_databricks_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            conn.close()
            latency_ms = round((_time.perf_counter() - t0) * 1000, 1)
            return {"status": "ok", "message": f"Connected ({latency_ms} ms)", "latency_ms": latency_ms}
        except Exception as exc:
            latency_ms = round((_time.perf_counter() - t0) * 1000, 1)
            return {"status": "error", "message": str(exc)[:200], "latency_ms": latency_ms}

    result["databricks"] = await asyncio.to_thread(_check_databricks)

    # 2. LLM availability
    def _check_llms():
        from backend.services.text2sql.generation.llm_registry import LLM_MODELS, _is_ollama_available
        ollama_up = _is_ollama_available()
        models = []
        for model_id, info in LLM_MODELS.items():
            provider = info["provider"]
            req = info.get("requires", "")
            if provider == "ollama":
                available = ollama_up
                reason = "Ollama reachable" if available else "Ollama not running"
            elif req:
                available = bool(os.getenv(req))
                reason = f"{req} set" if available else f"{req} not set"
            else:
                available = True
                reason = "No key required"
            models.append({
                "id": model_id,
                "display_name": info["display_name"],
                "provider": provider,
                "available": available,
                "reason": reason,
            })
        return models

    result["llm_models"] = await asyncio.to_thread(_check_llms)

    # 3. Knowledge base (RAG)
    def _check_rag():
        info: dict = {
            "configured": _rag_configured,
            "embed_model": _EMBED_MODEL if _rag_configured else None,
        }
        if _rag_configured:
            meta_size = os.path.getsize(_RAG_METADATA_PATH) if os.path.exists(_RAG_METADATA_PATH) else 0
            faiss_exists = os.path.exists(_RAG_FAISS_PATH)
            # Count chunks by line count of metadata jsonl
            chunk_count = 0
            if os.path.exists(_RAG_METADATA_PATH):
                with open(_RAG_METADATA_PATH) as f:
                    chunk_count = sum(1 for _ in f)
            # Most recent PDF in embed dir (if any)
            latest_file = None
            if _embed_dir and os.path.isdir(_embed_dir):
                pdf_times = []
                for fname in os.listdir(_embed_dir):
                    fpath = os.path.join(_embed_dir, fname)
                    if os.path.isfile(fpath):
                        pdf_times.append((os.path.getmtime(fpath), fname))
                if pdf_times:
                    pdf_times.sort(reverse=True)
                    mtime, fname = pdf_times[0]
                    from datetime import datetime
                    latest_file = {
                        "name": fname,
                        "updated": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                    }
            info.update({
                "status": "ok" if faiss_exists else "index_missing",
                "chunk_count": chunk_count,
                "metadata_size_kb": round(meta_size / 1024, 1),
                "faiss_index_exists": faiss_exists,
                "latest_file": latest_file,
            })
        else:
            info["status"] = "not_configured"
        return info

    result["knowledge_base"] = await asyncio.to_thread(_check_rag)

    return result


# ── Eval results ─────────────────────────────────────────────────────────────

@app.get("/eval/results")
async def get_eval_results():
    """Return the latest eval results from eval/eval_result/latest.json."""
    import glob as _glob

    eval_dir = os.path.join(
        os.path.dirname(__file__), "../../../eval/eval_result"
    )
    eval_dir = os.path.abspath(eval_dir)
    latest_path = os.path.join(eval_dir, "latest.json")

    if os.path.exists(latest_path):
        with open(latest_path) as f:
            return json.load(f)

    # Fall back to most recent individual files if latest.json doesn't exist
    files = sorted(_glob.glob(os.path.join(eval_dir, "*.json")), reverse=True)
    if not files:
        return {"error": "No eval results found. Run: python -m scripts.run_eval"}

    with open(files[0]) as f:
        return json.load(f)


# ── PDF → knowledge base ──────────────────────────────────────────────────────

@app.post("/upload/pdf")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported on this endpoint")
    if not _embed_dir:
        raise HTTPException(status_code=503, detail="RAG_EMBED_DIR is not configured")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        try:
            tmp.write(await file.read())
            tmp.flush()

            try:
                from ..rag.indexing.incremental import IncrementalIndexer
            except ImportError:
                from rag.indexing.incremental import IncrementalIndexer

            indexer = IncrementalIndexer(
                embed_dir=_embed_dir,
                embed_model_name=_EMBED_MODEL,
            )
            result = await asyncio.to_thread(indexer.add_pdf, tmp.name, file.filename)

            if not result["success"]:
                raise HTTPException(status_code=400, detail=f"Indexing failed: {result['error']}")

            return {
                "success": True,
                "message": f"PDF indexed into knowledge base",
                "filename": result["filename"],
                "chunks_added": result["chunks_added"],
                "total_vectors": result["total_vectors"],
            }
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
