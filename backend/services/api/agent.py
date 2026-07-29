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

try:
    from observability.trace_log import trace_start, trace_end
except ImportError:
    trace_start = trace_end = None


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
    trace_id: Optional[str] = None


# ── Traced agent runner ───────────────────────────────────────────────────────
def _run_agent(initial_state: dict) -> dict:
    trace_id = initial_state.get("trace_id") or str(uuid.uuid4())
    initial_state["trace_id"] = trace_id
    question = initial_state.get("question", "")

    if trace_start:
        trace_start(trace_id, question, llm_model=initial_state.get("llm_model"))

    t0 = time.perf_counter()
    result = _agent.invoke(initial_state)
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    if trace_end:
        trace_end(
            trace_id,
            route=result.get("route"),
            latency_ms=latency_ms,
            error=result.get("error"),
            final_answer=result.get("final_answer"),
            sql_query=result.get("sql_query"),
        )

    if audit:
        audit.agent_query(
            question,
            route=result.get("route"),
            sql_query=result.get("sql_query"),
            sql_table=result.get("sql_table"),
            session_id=initial_state.get("session_id"),
            user_id=initial_state.get("user_id"),
            llm_model=initial_state.get("llm_model"),
            latency_ms=latency_ms,
            error=result.get("error"),
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
    trace_id = str(uuid.uuid4())
    prog_queue = register(trace_id)

    initial_state: dict = {
        "question":         request.question,
        "history":          request.history,
        "llm_model":        request.llm_model,
        "session_id":       session_id,
        "trace_id":         trace_id,
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
                "trace_id":        trace_id,
            }})
        except Exception as e:
            prog_queue.put({"type": "error", "message": str(e)})
        finally:
            unregister(trace_id)

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
        trace_id=initial_state.get("trace_id"),
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

    error_count = sum(1 for r in audit_events if r.get("error"))
    success_rate = round((len(audit_events) - error_count) / len(audit_events) * 100, 1) if audit_events else None

    feedback_records = _tail_jsonl(_LIVE_FEEDBACK_FILE, max_lines=5000)
    good = sum(1 for f in feedback_records if f.get("rating") == "good")
    bad = sum(1 for f in feedback_records if f.get("rating") == "bad")
    total_feedback = good + bad

    # Raw per-query rows (already logged to the audit log) so the frontend can
    # derive trends, top-slow-queries, and a recent-traces table client-side
    # without any new instrumentation.
    recent_queries = [
        {
            "ts": r.get("ts"),
            "question": r.get("question"),
            "route": r.get("route") or "unknown",
            "latency_ms": r.get("latency_ms"),
            "llm_model": r.get("llm_model"),
            "sql_table": r.get("sql_table"),
        }
        for r in audit_events[-300:]
    ][::-1]

    return {
        "generated_at": now.isoformat(),
        "queries": {
            "total": len(audit_events),
            "recent": len(recent),
            "window_minutes": window_minutes,
            "by_route": by_route,
            "latest_ts": audit_events[-1]["ts"] if audit_events else None,
            "success_rate": success_rate,
            "error_count": error_count,
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
        "recent_queries": recent_queries,
    }


# ── Traces (LangChain/LangSmith-style run tree, in-house) ────────────────────
# Every agent run gets a trace_id (see backend/services/agent/progress.py and
# observability/trace_log.py). Nodes emit a span each time they start a unit
# of work; trace_start/trace_end bookend the run. This groups the raw span
# log into per-trace records and turns the point-in-time span markers into a
# waterfall of durations for the frontend.

_TRACE_LOG_PATH = _METRICS_ROOT / "observability" / "logs" / "traces.log"


def _load_traces(max_lines: int = 8000) -> dict[str, dict]:
    events = _tail_jsonl(_TRACE_LOG_PATH, max_lines=max_lines)
    traces: dict[str, dict] = {}
    for e in events:
        trace_id = e.get("trace_id")
        if not trace_id:
            continue
        t = traces.setdefault(trace_id, {"trace_id": trace_id, "spans": []})
        event = e.get("event")
        if event == "trace.start":
            t["question"] = e.get("question")
            t["start_ts"] = e.get("ts")
            t["llm_model"] = e.get("llm_model")
        elif event == "trace.span":
            t["spans"].append({"step": e.get("step"), "label": e.get("label"), "ts": e.get("ts")})
        elif event == "trace.end":
            t["end_ts"] = e.get("ts")
            t["route"] = e.get("route")
            t["latency_ms"] = e.get("latency_ms")
            t["error"] = e.get("error")
            t["final_answer"] = e.get("final_answer")
            t["sql_query"] = e.get("sql_query")
    return traces


def _spans_with_durations(t: dict) -> list[dict]:
    """A span's duration is the time until the next span (or trace end) begins —
    this pipeline runs its steps sequentially, so consecutive span timestamps
    are real start/end boundaries, not an approximation."""
    if "start_ts" not in t:
        return []
    spans_sorted = sorted(t["spans"], key=lambda s: s["ts"])
    start_ts = t["start_ts"]
    end_ts = t.get("end_ts") or (spans_sorted[-1]["ts"] if spans_sorted else start_ts)
    boundaries = [start_ts] + [s["ts"] for s in spans_sorted] + [end_ts]
    return [
        {
            "step": s["step"],
            "label": s["label"],
            "start_ms": round((s["ts"] - start_ts) * 1000, 1),
            "duration_ms": round(max(0.0, boundaries[i + 2] - s["ts"]) * 1000, 1),
        }
        for i, s in enumerate(spans_sorted)
    ]


@app.get("/traces")
async def list_traces(limit: int = 50, offset: int = 0, route: Optional[str] = None, q: Optional[str] = None):
    """Traces, newest first — one row per agent run. Optional route filter and
    free-text search over the question."""
    traces = [t for t in _load_traces().values() if "start_ts" in t]
    if route and route != "all":
        traces = [t for t in traces if (t.get("route") or "unknown") == route]
    if q:
        q_lower = q.lower()
        traces = [t for t in traces if q_lower in (t.get("question") or "").lower() or q_lower in t["trace_id"]]
    traces.sort(key=lambda t: t["start_ts"], reverse=True)

    page = traces[offset:offset + limit]
    return {
        "total": len(traces),
        "traces": [
            {
                "trace_id": t["trace_id"],
                "question": t.get("question"),
                "route": t.get("route"),
                "start_ts": t["start_ts"],
                "latency_ms": t.get("latency_ms"),
                "error": t.get("error"),
                "span_count": len(t["spans"]),
                "complete": "end_ts" in t,
            }
            for t in page
        ],
    }


@app.get("/traces/{trace_id}")
async def get_trace(trace_id: str):
    """A single trace's span waterfall/graph — a node's duration is the time until the next node starts."""
    t = _load_traces().get(trace_id)
    if not t or "start_ts" not in t:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans = _spans_with_durations(t)
    end_ts = t.get("end_ts") or (spans[-1]["start_ms"] / 1000 + t["start_ts"] if spans else t["start_ts"])

    return {
        "trace_id": trace_id,
        "question": t.get("question"),
        "route": t.get("route"),
        "llm_model": t.get("llm_model"),
        "error": t.get("error"),
        "final_answer": t.get("final_answer"),
        "sql_query": t.get("sql_query"),
        "complete": "end_ts" in t,
        "start_ts": t["start_ts"],
        "total_ms": round((end_ts - t["start_ts"]) * 1000, 1),
        "spans": spans,
    }


@app.get("/latency/stats")
async def latency_stats(slo_threshold_ms: int = 2000):
    """
    Aggregate latency view: overall percentiles + SLO compliance, a per-route
    breakdown (from the audit log), a per-pipeline-stage breakdown (from real
    span durations across all traces), and the traces whose single slowest
    stage ("bottleneck") took the longest — everything derived from data
    already logged, no separate instrumentation.
    """
    audit_events = [r for r in _tail_jsonl(_AUDIT_LOG_PATH, max_lines=8000) if r.get("event") == "agent.query"]
    all_latencies = [r["latency_ms"] for r in audit_events if r.get("latency_ms") is not None]

    by_route_latencies: dict[str, list[float]] = {}
    for r in audit_events:
        lat = r.get("latency_ms")
        if lat is None:
            continue
        route = r.get("route") or "unknown"
        by_route_latencies.setdefault(route, []).append(lat)

    total_count = len(all_latencies)
    by_route = [
        {
            "route": route,
            "count": len(lats),
            "pct_of_total": round(len(lats) / total_count * 100, 1) if total_count else 0,
            "p50": _percentile(lats, 50),
            "p95": _percentile(lats, 95),
            "p99": _percentile(lats, 99),
        }
        for route, lats in sorted(by_route_latencies.items(), key=lambda kv: -len(kv[1]))
    ]

    traces = _load_traces()
    stage_durations: dict[str, list[float]] = {}
    stage_labels: dict[str, str] = {}
    slowest_traces: list[dict] = []

    for t in traces.values():
        if "start_ts" not in t or "end_ts" not in t:
            continue
        spans = _spans_with_durations(t)
        if not spans:
            continue
        for s in spans:
            stage_durations.setdefault(s["step"], []).append(s["duration_ms"])
            stage_labels[s["step"]] = s["label"]

        bottleneck = max(spans, key=lambda s: s["duration_ms"])
        slowest_traces.append({
            "trace_id": t["trace_id"],
            "question": t.get("question"),
            "route": t.get("route"),
            "bottleneck_step": bottleneck["step"],
            "bottleneck_label": bottleneck["label"],
            "bottleneck_ms": bottleneck["duration_ms"],
            "total_ms": t.get("latency_ms"),
            "start_ts": t["start_ts"],
        })

    by_stage = [
        {
            "step": step,
            "label": stage_labels[step],
            "count": len(durs),
            "p50": _percentile(durs, 50),
            "p95": _percentile(durs, 95),
            "p99": _percentile(durs, 99),
        }
        for step, durs in stage_durations.items()
    ]
    sum_p95 = sum(s["p95"] for s in by_stage) or 1
    for s in by_stage:
        s["pct_of_p95"] = round(s["p95"] / sum_p95 * 100, 1)
    by_stage.sort(key=lambda s: -s["p95"])

    slowest_traces.sort(key=lambda s: -s["bottleneck_ms"])

    slo_count = sum(1 for l in all_latencies if l <= slo_threshold_ms)

    return {
        "overall": {
            "p50": _percentile(all_latencies, 50),
            "p95": _percentile(all_latencies, 95),
            "p99": _percentile(all_latencies, 99),
            "avg": round(sum(all_latencies) / total_count, 1) if total_count else 0,
            "slo_threshold_ms": slo_threshold_ms,
            "slo_compliance_pct": round(slo_count / total_count * 100, 1) if total_count else None,
        },
        "by_route": by_route,
        "by_stage": by_stage,
        "slowest_traces": slowest_traces[:5],
    }


@app.get("/quality/stats")
async def quality_stats():
    """
    Real, ground-truth-free quality signals: pass/fail rate from the audit
    log, live RAG faithfulness (token-grounding, scored on every RAG query —
    see observability/metrics/rag_quality.py), and user feedback (thumbs
    up/down) as a human-acceptance proxy. Offline eval metrics (Correctness,
    Groundedness, Completeness, etc. — which need a reference answer, see
    eval/metrics/) require `python -m scripts.run_eval` to have been run at
    least once; omitted here rather than faked when no run exists.
    """
    audit_events = [r for r in _tail_jsonl(_AUDIT_LOG_PATH, max_lines=8000) if r.get("event") == "agent.query"]
    total = len(audit_events)
    error_count = sum(1 for r in audit_events if r.get("error"))
    pass_rate = round((total - error_count) / total * 100, 1) if total else None

    by_route_counts: dict[str, dict] = {}
    for r in audit_events:
        route = r.get("route") or "unknown"
        d = by_route_counts.setdefault(route, {"count": 0, "errors": 0})
        d["count"] += 1
        if r.get("error"):
            d["errors"] += 1
    by_route = [
        {
            "route": route,
            "count": d["count"],
            "pct_of_total": round(d["count"] / total * 100, 1) if total else 0,
            "pass_rate": round((d["count"] - d["errors"]) / d["count"] * 100, 1) if d["count"] else None,
        }
        for route, d in sorted(by_route_counts.items(), key=lambda kv: -kv[1]["count"])
    ]

    feedback_records = _tail_jsonl(_LIVE_FEEDBACK_FILE, max_lines=5000)
    good = sum(1 for f in feedback_records if f.get("rating") == "good")
    bad = sum(1 for f in feedback_records if f.get("rating") == "bad")
    total_feedback = good + bad

    faithfulness = _live_rag_quality.summary() if _live_rag_quality else None
    worst_faithfulness = _live_rag_quality.worst(5) if _live_rag_quality else []

    return {
        "overall": {
            "pass_rate": pass_rate,
            "evaluated": total,
            "error_count": error_count,
        },
        "faithfulness": faithfulness,
        "human_acceptance": {
            "rated": total_feedback,
            "good": good,
            "bad": bad,
            "acceptance_rate": round(good / total_feedback * 100, 1) if total_feedback else None,
        },
        "by_route": by_route,
        "worst_faithfulness": worst_faithfulness,
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
