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
import tempfile
import threading
from typing import Optional

from dotenv import load_dotenv
import queue as _queue
import uuid

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
    from ..agent.graph import build_agent
    from ..agent.tools.rag_tool import run_rag
    from ..text2sql.generation.llm_registry import list_llm_models
    from ..text2sql.indexing.inverted_index import init_inverted_index
    from ..text2sql.indexing.product_index import init_product_index
    from ..text2sql.indexing.column_embedding_index import get_column_embedding_index
except ImportError:
    from db.databricks_service import DatabricksService
    from agent.graph import build_agent
    from agent.tools.rag_tool import run_rag
    from generation.llm_registry import list_llm_models
    from indexing.inverted_index import init_inverted_index
    from indexing.product_index import init_product_index
    from indexing.column_embedding_index import get_column_embedding_index

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

# Inverted index — loaded from disk or built in background thread.
# sql_node falls back gracefully until ready (is_ready() returns False while building).
_value_index = init_inverted_index(
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

# Build the compiled LangGraph agent once at startup
_agent = build_agent(
    data_service=_data_service,
    metadata_path=_RAG_METADATA_PATH,
    faiss_path=_RAG_FAISS_PATH,
    embed_model_name=_EMBED_MODEL,
    reranker_model_name=_RERANKER_MODEL,
    value_index=_value_index,
    product_index=_product_index,
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
            _tl_run_id.value = None
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
        _tl_run_id.value = None
        result = await asyncio.to_thread(_run_agent, initial_state)
        run_id = getattr(_tl_run_id, "value", None)
        trace_url = await asyncio.to_thread(_share_run, run_id)
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
        from ..text2sql.db.upload_service import UploadService
        from ..text2sql.retrieval.table_matching import invalidate_table_cache
    except ImportError:
        from text2sql.db.upload_service import UploadService
        from text2sql.retrieval.table_matching import invalidate_table_cache

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
