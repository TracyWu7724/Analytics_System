"""
api/agent.py — v2 FastAPI endpoint for the combined Text2SQL + RAG agent.

POST /agent/query
    Accepts a question and returns the agent's answer, routing decision,
    SQL query (if used), retrieved chunks (if used), and a LangSmith trace URL.
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
    from ..agent.graph import build_agent
    from ..agent.tools.rag_tool import run_rag
    from ..text2sql.generation.llm_registry import list_llm_models
except ImportError:
    from db.databricks_service import DatabricksService
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


@app.post("/agent/query", response_model=AgentQueryResponse)
async def agent_query(request: AgentQueryRequest):
    initial_state = {
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
    }

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
