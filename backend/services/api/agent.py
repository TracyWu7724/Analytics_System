"""
api/agent.py — v2 FastAPI endpoint for the combined Text2SQL + RAG agent.

POST /agent/query
    Accepts a question and returns the agent's answer, routing decision,
    SQL query (if used), and retrieved chunks (if used). Each call is logged
    to observability/audit_logger.py with latency, route, sql_query, sql_table,
    session_id, user_id, llm_model, and question.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import queue as _queue
import uuid

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

# ── Tracing (in-house — latency + structured audit log, no external service) ─
import time

try:
    from observability.audit_logger import audit
except ImportError:
    audit = None


# ── Service imports ──────────────────────────────────────────────────────────
try:
    from ..text2sql.db.databricks_service import DatabricksService
    from ..agent.graph import build_agent
    from ..agent.tools.rag_tool import run_rag
    from ..text2sql.generation.llm_registry import list_llm_models
    from ..text2sql.indexing.hybrid_value_index import init_hybrid_index
    from ..text2sql.indexing.inverted_index import init_inverted_index
    from ..text2sql.indexing.product_index import init_product_index
    from ..text2sql.indexing.column_embedding_index import get_column_embedding_index
    from ..text2sql.mdl.mdl_loader import load_mdl
    from ..rag.kg.knowledge_graph import KnowledgeGraph
    from ..rag.kg.kg_builder import KGBuilder
except ImportError:
    from db.databricks_service import DatabricksService
    from agent.graph import build_agent
    from agent.tools.rag_tool import run_rag
    from generation.llm_registry import list_llm_models
    from indexing.hybrid_value_index import init_hybrid_index
    from indexing.inverted_index import init_inverted_index
    from indexing.product_index import init_product_index
    from indexing.column_embedding_index import get_column_embedding_index
    from mdl_loader import load_mdl
    from rag.kg.knowledge_graph import KnowledgeGraph
    from rag.kg.kg_builder import KGBuilder

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

# Warm schema cache in background so column-based table scoring works from first query
def _warm_schema_cache():
    import threading
    def _warm():
        try:
            tables = _data_service.get_table_names()
            for t in tables:
                _data_service.get_table_schema(t)
        except Exception:
            pass
    threading.Thread(target=_warm, daemon=True).start()

_warm_schema_cache()

# Value index — hybrid wrapper over InvertedIndex with canonicalization + profiling.
# Falls back gracefully until ready (is_ready() returns False while building).
_value_index = init_hybrid_index(
    _data_service,
    index_dir=os.getenv("INDEX_DIR", ""),
    embed_model_name=os.getenv("RAG_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
)

_product_index = init_product_index(
    _data_service,
    index_dir=os.getenv("INDEX_DIR", ""),
)

# Column embedding index — load from disk if available, else build in background.
_col_emb_index = get_column_embedding_index(
    index_dir=os.getenv("INDEX_DIR", "") or str(
        __import__("pathlib").Path(__file__).resolve().parents[3] / "backend" / "index"
    ),
    embed_model_name=os.getenv("RAG_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
)
if not _col_emb_index.is_ready():
    _col_emb_index.build(_data_service, background=True)

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

# MDL semantic layer — loaded once at startup; hot-reloadable via /mdl/reload
_mdl = load_mdl()
if _mdl:
    print(f"MDL loaded: {len(_mdl.metrics)} metrics, {len(_mdl.joins)} joins")
else:
    print("MDL not found — SQL generation will proceed without semantic layer")

# Knowledge Graph — load from disk if available, build async otherwise
_KG_PATH = os.path.join(os.getenv("INDEX_DIR", "") or str(
    __import__("pathlib").Path(__file__).resolve().parents[3] / "index"
), "knowledge_graph.json")
_kg = KnowledgeGraph()
if not _kg.load(_KG_PATH):
    print("KG not found — will be built when PDFs are uploaded")
else:
    print(f"KG loaded: {_kg.stats()}")

# Build the compiled LangGraph agent once at startup
_agent = build_agent(
    data_service=_data_service,
    metadata_path=_RAG_METADATA_PATH,
    faiss_path=_RAG_FAISS_PATH,
    embed_model_name=_EMBED_MODEL,
    reranker_model_name=_RERANKER_MODEL,
    value_index=_value_index,
    product_index=_product_index,
    kg=_kg,
)


# ── Request / Response models ─────────────────────────────────────────────────
class AgentQueryRequest(BaseModel):
    question: str
    llm_model: str = "gpt-5.4"
    history: list[dict] = []
    session_id: Optional[str] = None


class FeedbackRequest(BaseModel):
    message_id: str
    question: str
    sql: Optional[str] = None
    final_answer: Optional[str] = None
    rating: str                         # "good" | "bad"
    comment: str = ""
    session_id: str = ""
    route: str = ""                     # "sql" | "rag" | "both" | "schema"
    history: list[dict] = []            # conversation snapshot at time of rating


class RagQueryRequest(BaseModel):
    question: str
    llm_model: str = "gpt-5.4"
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
    rag_verification: Optional[dict] = None
    error: Optional[str] = None
    trace_url: Optional[str] = None


# ── Traced agent runner ───────────────────────────────────────────────────────
def _run_agent(initial_state: dict) -> dict:
    t0 = time.perf_counter()
    result = _agent.invoke(initial_state)
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    if audit:
        audit.agent_query(
            initial_state.get("question", ""),
            route=result.get("route"),
            sql_query=result.get("sql_query"),
            sql_table=result.get("sql_table"),
            session_id=initial_state.get("session_id"),
            user_id=initial_state.get("user_id"),
            llm_model=initial_state.get("llm_model"),
            latency_ms=latency_ms,
        )
    return result


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


@app.post("/agent/query/stream")
async def agent_query_stream(
    request: AgentQueryRequest,
    authorization: Optional[str] = Header(default=None),
):
    """
    SSE endpoint — streams progress events then the final result.

    Event format:
      data: {"type": "progress", "step": "generating", "label": "Generating SQL..."}
      data: {"type": "result",   "data": { ...AgentQueryResponse fields... }}
      data: {"type": "error",    "message": "..."}
    """
    try:
        from ..agent.progress import register, unregister
    except ImportError:
        from agent.progress import register, unregister

    session_id = request.session_id or str(uuid.uuid4())
    prog_queue = register(session_id)

    initial_state: dict = {
        "question":         request.question,
        "history":          request.history,
        "llm_model":        request.llm_model,
        "session_id":       session_id,
        "user_id":          "",
        "uploaded_table":   None,
        "route":            None,
        "route_reasoning":  None,
        "sql_table":        None,
        "sql_tables":       None,
        "sql_query":        None,
        "sql_rows":         None,
        "sql_error":        None,
        "sql_attempts":     0,
        "rag_answer":       None,
        "rag_chunks":       None,
        "rag_error":        None,
        "rag_verification": None,
        "final_answer":     None,
        "error":            None,
        "denied_tables":    [],
        "denied_rag_sources": [],
    }

    try:
        from auth.permission_auth import auth_service
        if authorization:
            token = authorization.replace("Bearer ", "").strip()
            user = auth_service.verify_token(token)
            if user:
                initial_state["user_id"] = user.username
                initial_state = user.adjust_agent_state(initial_state)
    except Exception:
        pass

    def _run():
        try:
            result = _run_agent(initial_state)
            prog_queue.put({"type": "result", "data": {
                "question":        request.question,
                "route":           result.get("route"),
                "route_reasoning": result.get("route_reasoning"),
                "final_answer":    result.get("final_answer"),
                "sql_query":       result.get("sql_query"),
                "sql_rows":        result.get("sql_rows"),
                "sql_table":       result.get("sql_table"),
                "sql_attempts":    result.get("sql_attempts", 0),
                "rag_chunks":      result.get("rag_chunks"),
                "rag_verification":result.get("rag_verification"),
                "error":           result.get("error"),
                "trace_url":       None,
            }})
        except Exception as e:
            prog_queue.put({"type": "error", "message": str(e)})
        finally:
            unregister(session_id)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.to_thread(prog_queue.get, True, 1.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") in ("result", "error"):
                        break
                except _queue.Empty:
                    yield "data: {\"type\":\"heartbeat\"}\n\n"
        except asyncio.CancelledError:
            unregister(session_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/agent/query", response_model=AgentQueryResponse)
async def agent_query(request: AgentQueryRequest, authorization: Optional[str] = Header(default=None)):
    initial_state: dict = {
        "question": request.question,
        "history": request.history,
        "llm_model": request.llm_model,
        "session_id": request.session_id or "",
        "user_id": "",
        "uploaded_table": None,
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
        "rag_verification": None,
        "final_answer": None,
        "error": None,
        "denied_tables": [],
        "denied_rag_sources": [],
    }

    # Apply data-level access restrictions if the user is authenticated
    try:
        from auth.permission_auth import auth_service
        if authorization:
            token = authorization.replace("Bearer ", "").strip()
            user = auth_service.verify_token(token)
            if user:
                initial_state["user_id"] = user.username
                initial_state = user.adjust_agent_state(initial_state)
    except Exception:
        pass  # auth module unavailable — serve without restrictions

    try:
        # Run agent synchronously (LangGraph is sync); offload to thread so we
        # don't block the event loop
        result = await asyncio.to_thread(_run_agent, initial_state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    sql_table = result.get("sql_table")
    return AgentQueryResponse(
        question=request.question,
        route=result.get("route"),
        route_reasoning=result.get("route_reasoning"),
        final_answer=result.get("final_answer"),
        sql_query=result.get("sql_query"),
        sql_rows=result.get("sql_rows"),
        sql_table=sql_table,
        sql_attempts=result.get("sql_attempts", 0),
        rag_chunks=result.get("rag_chunks"),
        rag_verification=result.get("rag_verification"),
        error=result.get("error"),
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


@app.get("/table/{table_name}/preview")
async def get_table_preview(table_name: str, limit: int = 5):
    try:
        return _data_service.get_table_preview(table_name, limit)
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
                _data_service.http_path,
                _data_service.token,
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

        # Inverted index stats (schema + value + history)
        try:
            from ..text2sql.indexing.inverted_index import get_inverted_index
            idx = get_inverted_index()
            if idx is not None:
                info["inverted_index"] = idx.stats()
            else:
                info["inverted_index"] = None
        except Exception:
            info["inverted_index"] = None

        return info

    result["knowledge_base"] = await asyncio.to_thread(_check_rag)

    return result


# ── Index management ─────────────────────────────────────────────────────────

@app.post("/index/rebuild")
async def rebuild_index():
    """Trigger a background rebuild of the value/schema inverted index and the
    product index.  Call this after any data change in Databricks.
    """
    try:
        from ..text2sql.indexing.inverted_index import get_inverted_index
        from ..text2sql.indexing.product_index import get_product_index
    except ImportError:
        from text2sql.indexing.inverted_index import get_inverted_index
        from text2sql.indexing.product_index import get_product_index

    results = {}

    idx = get_inverted_index()
    if idx is not None:
        idx.rebuild(_data_service, background=True)
        results["value_index"] = "rebuild started"
    else:
        results["value_index"] = "not initialised"

    pidx = get_product_index()
    if pidx is not None:
        pidx.rebuild(_data_service, background=True)
        results["product_index"] = "rebuild started"
    else:
        results["product_index"] = "not initialised"

    try:
        from ..text2sql.indexing.column_embedding_index import get_column_embedding_index
    except ImportError:
        from text2sql.indexing.column_embedding_index import get_column_embedding_index
    col_idx = get_column_embedding_index()
    col_idx.build(_data_service, background=True)
    results["column_embeddings"] = "rebuild started"

    return {"success": True, "message": "Index rebuild started in background", "details": results}


@app.get("/index/products")
async def list_products(query: Optional[str] = None, limit: int = 50):
    """Browse the product index.  Pass ?query=243 to search for a specific product."""
    try:
        from ..text2sql.indexing.product_index import get_product_index
    except ImportError:
        from text2sql.indexing.product_index import get_product_index

    pidx = get_product_index()
    if pidx is None or not pidx.is_ready():
        raise HTTPException(status_code=503, detail="Product index not ready")

    if query:
        hits = pidx.search(query)[:limit]
        return {
            "query": query,
            "results": [
                {
                    "full_name":  r.full_name,
                    "table":      r.table,
                    "brand":      r.brand,
                    "number":     r.number,
                    "descriptor": r.descriptor,
                    "variants":   r.variants,
                }
                for r in hits
            ],
        }

    return {"stats": pidx.stats(), "sample": pidx.dump_variants(limit=limit)}


# ── Eval results ─────────────────────────────────────────────────────────────

@app.get("/eval/results")
async def get_eval_results():
    """Return the latest eval results from eval/eval_result/latest.jsonl."""
    import glob as _glob

    eval_dir = os.path.join(
        os.path.dirname(__file__), "../../../eval/eval_result"
    )
    eval_dir = os.path.abspath(eval_dir)

    def _read_jsonl(path: str) -> dict:
        """Parse a JSONL file: first line is summary header, rest are row objects."""
        rows: list[dict] = []
        meta: dict = {}
        with open(path) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if i == 0 and obj.get("_meta"):
                    meta = obj
                else:
                    rows.append(obj)
        result = {k: v for k, v in meta.items() if k not in ("_meta",)}
        result["rows"] = rows
        return result

    # Prefer latest.jsonl (new format), fall back to latest.json (legacy)
    latest_jsonl = os.path.join(eval_dir, "latest.jsonl")
    latest_json  = os.path.join(eval_dir, "latest.json")

    if os.path.exists(latest_jsonl):
        with open(latest_jsonl) as f:
            return json.loads(f.readline().strip())

    if os.path.exists(latest_json):
        with open(latest_json) as f:
            return json.load(f)

    # Fall back to most recent per-eval JSONL
    files = sorted(_glob.glob(os.path.join(eval_dir, "*.jsonl")), reverse=True)
    if files:
        return _read_jsonl(files[0])

    # Last resort: legacy JSON files
    files = sorted(_glob.glob(os.path.join(eval_dir, "*.json")), reverse=True)
    if files:
        with open(files[0]) as f:
            return json.load(f)

    return {"error": "No eval results found. Run: python -m scripts.run_eval"}


@app.get("/eval/rows")
async def get_eval_rows():
    """Return per-row eval results from the most recent per-eval JSONL files."""
    import glob as _glob

    eval_dir = os.path.join(
        os.path.dirname(__file__), "../../../eval/eval_result"
    )
    eval_dir = os.path.abspath(eval_dir)

    def _read_jsonl_rows(path: str) -> tuple[list[dict], dict]:
        rows: list[dict] = []
        meta: dict = {}
        with open(path) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if i == 0 and obj.get("_meta"):
                    meta = obj
                else:
                    rows.append(obj)
        return rows, meta

    # Find most recent file for each eval type
    eval_types = ["eval_text2sql", "eval_agentic", "eval_llms", "eval_rag_perf"]
    result: dict = {}

    for eval_type in eval_types:
        pattern = os.path.join(eval_dir, f"{eval_type}_*.jsonl")
        files = sorted(_glob.glob(pattern), reverse=True)
        if files:
            rows, meta = _read_jsonl_rows(files[0])
            result[eval_type] = {
                "rows": rows,
                "summary": meta.get("summary", {}),
                "timestamp": meta.get("timestamp", ""),
            }

    if not result:
        return {"error": "No per-eval JSONL files found. Run: python -m scripts.run_eval"}

    return result


# ── Live metrics (real-time evaluation dashboard) ─────────────────────────────
# Aggregates the two "online evaluation" signals described in
# docs/evaluation.md — the audit log (query volume + latency, per route) and
# eval/user_feedback.jsonl (thumbs up/down) — which today are append-only
# files with no aggregation anywhere else.

_METRICS_ROOT = Path(__file__).resolve().parents[3]
_AUDIT_LOG_PATH = _METRICS_ROOT / "observability" / "logs" / "audit.log"
_LIVE_FEEDBACK_FILE = _METRICS_ROOT / "eval" / "user_feedback.jsonl"

try:
    from observability.metrics.costs import cost_tracker as _live_cost_tracker
except Exception:
    _live_cost_tracker = None

try:
    from observability.metrics.rag_quality import rag_quality_tracker as _live_rag_quality
except Exception:
    _live_rag_quality = None


def _tail_jsonl(path: Path, max_lines: int = 2000) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", errors="ignore") as f:
        lines = f.readlines()[-max_lines:]
    records: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    frac = k - lo
    return round(values[lo] + frac * (values[hi] - values[lo]), 1)


@app.get("/metrics/live")
async def get_live_metrics(window_minutes: int = 15):
    """Real-time evaluation metrics derived from live traffic: query volume,
    latency, and user feedback, refreshed on every call so the frontend can
    poll it for a live dashboard."""
    audit_events = [r for r in _tail_jsonl(_AUDIT_LOG_PATH) if r.get("event") == "agent.query"]

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=window_minutes)

    def _parse_ts(r: dict):
        try:
            return datetime.fromisoformat(r["ts"])
        except Exception:
            return None

    recent = [r for r in audit_events if (ts := _parse_ts(r)) and ts >= cutoff]

    all_latencies = [r["latency_ms"] for r in audit_events if r.get("latency_ms") is not None]
    recent_latencies = [r["latency_ms"] for r in recent if r.get("latency_ms") is not None]

    by_route: dict[str, int] = {}
    for r in audit_events:
        route = r.get("route") or "unknown"
        by_route[route] = by_route.get(route, 0) + 1

    feedback_records = _tail_jsonl(_LIVE_FEEDBACK_FILE, max_lines=5000)
    good = sum(1 for f in feedback_records if f.get("rating") == "good")
    bad = sum(1 for f in feedback_records if f.get("rating") == "bad")
    total_feedback = good + bad

    return {
        "generated_at": now.isoformat(),
        "queries": {
            "total": len(audit_events),
            "recent": len(recent),
            "window_minutes": window_minutes,
            "by_route": by_route,
            "latest_ts": audit_events[-1]["ts"] if audit_events else None,
        },
        "latency_ms": {
            "avg": round(sum(all_latencies) / len(all_latencies), 1) if all_latencies else 0,
            "p50": _percentile(all_latencies, 50),
            "p95": _percentile(all_latencies, 95),
            "recent_avg": round(sum(recent_latencies) / len(recent_latencies), 1) if recent_latencies else 0,
        },
        "feedback": {
            "total": total_feedback,
            "good": good,
            "bad": bad,
            "satisfaction_rate": round(good / total_feedback * 100, 1) if total_feedback else None,
        },
        "cost": _live_cost_tracker.summary() if _live_cost_tracker else None,
        "rag": {
            # Faithfulness (token-grounding) is the one eval/metrics/ RAG
            # metric computable without ground truth, so it's the only one
            # scored on live traffic — see eval/metrics/_faithfulness_core.py.
            # Accuracy, AnswerRelevancy, and the three Contextual* metrics all
            # need a reference answer or "ideal chunks" from eval/dataset/*.csv
            # and only run through the offline eval driver.
            "faithfulness": _live_rag_quality.summary() if _live_rag_quality else None,
        },
    }


# ── Feedback ─────────────────────────────────────────────────────────────────

@app.post("/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Store thumbs-up/down feedback for a message."""
    try:
        from ..text2sql.generation.sql_hallucination_guard import store_feedback
    except ImportError:
        from text2sql.generation.sql_hallucination_guard import store_feedback

    user_id = ""
    try:
        from auth.permission_auth import auth_service
        if authorization:
            token = authorization.replace("Bearer ", "").strip()
            user = auth_service.verify_token(token)
            if user:
                user_id = user.username
    except Exception:
        pass

    store_feedback(
        message_id=request.message_id,
        question=request.question,
        sql=request.sql,
        final_answer=request.final_answer,
        rating=request.rating,
        comment=request.comment,
        session_id=request.session_id,
        user_id=user_id,
        route=request.route,
        history=request.history,
    )
    return {"success": True}


# ── CSV / Excel → local SQLite ────────────────────────────────────────────────

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    if not any(file.filename.lower().endswith(ext) for ext in [".csv", ".xlsx", ".xls"]):
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

    try:
        from backend.services.text2sql.db.upload_service import UploadService
        from backend.services.text2sql.retrieval.table_matching import invalidate_table_cache
    except ImportError:
        from ..text2sql.db.upload_service import UploadService
        from ..text2sql.retrieval.table_matching import invalidate_table_cache

    upload_service = UploadService(_data_service)

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        try:
            tmp.write(await file.read())
            tmp.flush()
            result = upload_service.process_uploaded_file(tmp.name, file.filename)
            if not result["success"]:
                raise HTTPException(status_code=400, detail=f"File processing failed: {result['error']}")
            invalidate_table_cache()
            return {
                "message": "File uploaded successfully",
                "table_name": result["table_name"],
                "row_count": result["row_count"],
                "column_count": result["column_count"],
                "columns": result["columns"],
                "original_filename": result.get("original_filename"),
            }
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


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
                from backend.services.rag.indexing.incremental import IncrementalIndexer
            except ImportError:
                from ..rag.indexing.incremental import IncrementalIndexer

            indexer = IncrementalIndexer(
                embed_dir=_embed_dir,
                embed_model_name=_EMBED_MODEL,
                kg=_kg,
                kg_path=_KG_PATH,
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


# ── MDL endpoints ─────────────────────────────────────────────────────────────

@app.get("/mdl/config")
async def mdl_config():
    """Return the current MDL semantic layer configuration."""
    mdl = load_mdl()
    if mdl is None:
        return {"status": "not_configured"}
    return {
        "status": "ok",
        "version": mdl.version,
        "metrics": [{"name": m.name, "expression": m.expression, "synonyms": m.synonyms} for m in mdl.metrics],
        "joins": [{"left": j.left_table, "right": j.right_table, "on": j.on} for j in mdl.joins],
    }


@app.post("/mdl/reload")
async def mdl_reload():
    """Force a reload of the MDL schema.yaml from disk."""
    global _mdl
    try:
        from ..text2sql.mdl.mdl_loader import _cache_mtime
        import backend.services.text2sql.mdl.mdl_loader as _mdl_mod
        _mdl_mod._cache_config = None
        _mdl_mod._cache_mtime = 0.0
        _mdl = load_mdl()
        if _mdl:
            return {"status": "reloaded", "metrics": len(_mdl.metrics), "joins": len(_mdl.joins)}
        return {"status": "not_found"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


# ── KG endpoints ──────────────────────────────────────────────────────────────

@app.get("/kg/stats")
async def kg_stats():
    """Return knowledge graph statistics."""
    return {"status": "ok", **_kg.stats()}
