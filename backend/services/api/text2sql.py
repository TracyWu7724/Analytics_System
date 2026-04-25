import asyncio
import io
import os
import sqlite3
import tempfile
import threading
from datetime import datetime
from typing import Optional

import pandas as pd
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# Load .env FIRST so LANGCHAIN_API_KEY is available before anything else reads it
load_dotenv()

# LangSmith tracing — optional; silently disabled when the API key is absent
_LANGSMITH_ENABLED = bool(os.getenv("LANGCHAIN_API_KEY"))
_ls_client = None

try:
    from langsmith import Client, traceable
    from langsmith.run_helpers import get_current_run_tree

    if _LANGSMITH_ENABLED:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        _ls_client = Client()
except ImportError:
    _LANGSMITH_ENABLED = False


def _share_run(run_id: Optional[str]) -> Optional[str]:
    """Return a public LangSmith URL for run_id, or None if unavailable.

    LangSmith ingests runs asynchronously, so we flush the local buffer then
    retry a few times to give the server time to process the run before sharing.
    """
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


_tl_run_id = threading.local()  # stores the last captured run_id per thread

try:
    from ..text2sql.db.databricks_service import DatabricksService
    from ..text2sql.db.upload_service import UploadService
    from ..text2sql.generation.llm_registry import list_llm_models
    from ..text2sql.generation.sql_correction import clean_sql_query
    from ..text2sql.generation.sql_generation import detect_large_dataset_request, generate_sql
    from ..text2sql.indexing.history_question_indexing import ensure_sql_column, index_question_background
    from ..text2sql.models import QueryRequest
    from ..text2sql.retrieval.history_question_retrieval import get_relevant_query_history
    from ..text2sql.retrieval.table_matching import extract_table_name_from_question, get_all_available_tables, get_relevant_tables, invalidate_table_cache
except ImportError:
    from db.databricks_service import DatabricksService
    from db.upload_service import UploadService
    from generation.llm_registry import list_llm_models
    from generation.sql_correction import clean_sql_query
    from generation.sql_generation import detect_large_dataset_request, generate_sql
    from indexing.history_question_indexing import ensure_sql_column, index_question_background
    from models import QueryRequest
    from retrieval.history_question_retrieval import get_relevant_query_history
    from retrieval.table_matching import extract_table_name_from_question, get_all_available_tables, get_relevant_tables, invalidate_table_cache

try:
    from observability.metrics.costs import cost_tracker
    from observability.metrics.sys_perf import perf
    _METRICS_ENABLED = True
except Exception:
    cost_tracker = None
    perf = None
    _METRICS_ENABLED = False


app = FastAPI(title="SQL Query API", description="API for natural language to SQL queries", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Latency middleware — records every request under "http.<METHOD>.<path>"
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

class LatencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        if perf is not None:
            operation = f"http.{request.method}.{request.url.path}"
            async with perf.ameasure(operation):
                return await call_next(request)
        return await call_next(request)

app.add_middleware(LatencyMiddleware)

last_query_results: list[dict] = []
data_service = DatabricksService()
data_service.init_local_db()
ensure_sql_column(data_service.local_db_path)
upload_service = UploadService(data_service)

try:
    from ..text2sql.indexing.inverted_index import init_inverted_index as _init_idx
    _init_idx(data_service)   # loads from backend/index/ or rebuilds in background
except Exception:
    pass


# ---------------------------------------------------------------------------
# Traced SQL generation (no-op wrapper when LangSmith is disabled)
# ---------------------------------------------------------------------------

if _LANGSMITH_ENABLED:
    @traceable(run_type="chain", name="text2sql-pipeline")
    def _traced_generate_sql(question, table_name, columns, custom_limit, llm_model):
        rt = get_current_run_tree()
        _tl_run_id.value = str(rt.id) if rt else None
        raw_sql = generate_sql(question, table_name, columns, custom_limit, llm_model)
        return clean_sql_query(raw_sql)
else:
    def _traced_generate_sql(question, table_name, columns, custom_limit, llm_model):
        _tl_run_id.value = None
        raw_sql = generate_sql(question, table_name, columns, custom_limit, llm_model)
        return clean_sql_query(raw_sql)


def get_table_columns(table_name: str) -> list[str] | None:
    if table_name.startswith("uploaded_"):
        return upload_service.get_uploaded_table_columns(table_name, data_service.local_db_path)

    schema = data_service.get_table_schema(table_name)
    return [col["name"] for col in schema] if schema else None


def prepare_question(question: str, uploaded_table: str | None) -> tuple[str, str, list[dict], list[dict]]:
    table_candidates = [] if uploaded_table else get_relevant_tables(question, data_service, limit=3)
    related_queries = get_relevant_query_history(question, data_service, limit=3)
    table_name = uploaded_table or (table_candidates[0]["full_name"] if table_candidates else extract_table_name_from_question(question, data_service))

    if uploaded_table:
        prepared_question = (
            f"Using the uploaded table '{uploaded_table}', {question}. "
            "Use simple SQL syntax suitable for SQLite, not T-SQL. Do not use fully qualified table names."
        )
    else:
        prepared_question = question

    return prepared_question, table_name, table_candidates, related_queries


@app.get("/")
async def root():
    return {
        "message": "SQL Query API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "GET /health": "Health check",
            "GET /llm-models": "Available LLM models",
            "POST /generate_sql": "Generate SQL from natural language",
            "POST /query": "Generate and execute natural language query",
            "POST /upload": "Upload CSV/Excel file",
            "GET /tables": "List tables",
        },
    }


@app.get("/llm-models")
async def get_llm_models():
    return list_llm_models()


@app.get("/health")
async def health_check():
    result = data_service.test_connection()
    if result["status"] != "success":
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    if not any(file.filename.lower().endswith(ext) for ext in [".csv", ".xlsx", ".xls"]):
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
        try:
            temp_file.write(await file.read())
            temp_file.flush()
            result = upload_service.process_uploaded_file(temp_file.name, file.filename)
            if not result["success"]:
                raise HTTPException(status_code=400, detail=f"File processing failed: {result['error']}")

            invalidate_table_cache()
            preview_data = data_service.query_uploaded_table(f"SELECT * FROM {result['table_name']} LIMIT 10")
            return {
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
                os.unlink(temp_file.name)
            except OSError:
                pass


@app.get("/recent_queries")
async def get_recent_queries():
    return {"recent_queries": data_service.get_recent_queries(5)}


@app.get("/table/{table_name}/preview")
async def get_table_preview(table_name: str, limit: int = 5):
    try:
        if table_name.startswith("uploaded_"):
            conn = sqlite3.connect(data_service.local_db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
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
                **data_service.get_table_metadata(table_name),
            }

        return data_service.get_table_preview(table_name, limit)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching table preview: {e}")


@app.post("/generate_sql")
async def generate_sql_endpoint(request: QueryRequest):
    try:
        is_large_request, custom_limit, _ = detect_large_dataset_request(request.question)
        question, table_name, table_candidates, related_queries = prepare_question(request.question, request.uploaded_table)

        _tl_run_id.value = None
        # Run sync in event loop thread so _tl_run_id.value is set in the same thread we read it from
        sql_query = _traced_generate_sql(question, table_name, get_table_columns(table_name), custom_limit, request.llm_model)
        # Offload the flush+retry wait to a thread so we don't block the event loop
        run_id = getattr(_tl_run_id, "value", None)
        trace_url = await asyncio.to_thread(_share_run, run_id)

        response = {
            "question": request.question,
            "sql_query": sql_query,
            "table_name": table_name,
            "table_candidates": table_candidates,
            "related_queries": related_queries,
            "trace_url": trace_url,
        }
        if is_large_request:
            response["warning"] = "Large result set requested; execution may take longer than usual."
        return response
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL Generation Error: {e}")


@app.post("/query")
async def execute_natural_language_query(request: QueryRequest, background_tasks: BackgroundTasks):
    global last_query_results

    try:
        is_large_request, custom_limit, suggested_timeout = detect_large_dataset_request(request.question)
        question, table_name, table_candidates, related_queries = prepare_question(request.question, request.uploaded_table)

        _tl_run_id.value = None
        sql_query = _traced_generate_sql(question, table_name, get_table_columns(table_name), custom_limit, request.llm_model)
        run_id = getattr(_tl_run_id, "value", None)
        trace_url = await asyncio.to_thread(_share_run, run_id)

        if table_name.startswith("uploaded_"):
            result_rows = data_service.query_uploaded_table(sql_query)
        else:
            result_rows = data_service.execute_query(sql_query, timeout_seconds=min(suggested_timeout, 300), custom_limit=custom_limit)

        last_query_results = result_rows
        _index_table = table_name if not table_name.startswith("uploaded_") else ""
        background_tasks.add_task(
            index_question_background, request.question, data_service, sql_query, _index_table
        )

        response = {
            "question": request.question,
            "sql_query": sql_query,
            "rows": result_rows,
            "count": len(result_rows),
            "raw_result": f"Retrieved {len(result_rows)} rows",
            "table_candidates": table_candidates,
            "related_queries": related_queries,
            "trace_url": trace_url,
        }
        if is_large_request:
            response["warning"] = "Large result set requested; execution may take longer than usual."
        return response
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query Error: {e}")


@app.get("/download/csv")
async def download_csv():
    if not last_query_results:
        raise HTTPException(status_code=404, detail="No query results available for download")

    csv_buffer = io.StringIO()
    pd.DataFrame(last_query_results).to_csv(csv_buffer, index=False)
    filename = f"query_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(content=csv_buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.get("/download/excel")
async def download_excel():
    if not last_query_results:
        raise HTTPException(status_code=404, detail="No query results available for download")

    excel_buffer = io.BytesIO()
    df = pd.DataFrame(last_query_results)
    try:
        with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
            df.to_excel(writer, sheet_name="Query Results", index=False)
    except Exception:
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Query Results", index=False)

    filename = f"query_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=excel_buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/tables")
async def get_tables(include_sql_server: bool = False):
    try:
        if include_sql_server:
            tables = get_all_available_tables(data_service)
            return {
                "tables": tables,
                "total_count": len(tables),
                "uploaded_count": len([t for t in tables if t["source"] == "uploaded"]),
                "sql_server_count": len([t for t in tables if t["source"] != "uploaded"]),
                "sql_server_included": True,
            }

        uploaded_tables = data_service.get_uploaded_tables()
        return {
            "tables": uploaded_tables,
            "total_count": len(uploaded_tables),
            "uploaded_count": len(uploaded_tables),
            "sql_server_count": 0,
            "sql_server_included": False,
        }
    except Exception as e:
        return {"tables": [], "error": str(e)}


@app.get("/tables/uploaded")
async def get_uploaded_tables_only():
    try:
        uploaded_tables = data_service.get_uploaded_tables()
        return {"tables": uploaded_tables, "count": len(uploaded_tables), "source": "local_sqlite_only"}
    except Exception as e:
        return {"tables": [], "error": str(e)}


@app.delete("/tables/uploaded/{table_name}")
async def delete_uploaded_table(table_name: str):
    if not table_name.startswith("uploaded_"):
        raise HTTPException(status_code=400, detail="Only uploaded tables can be deleted")

    result = data_service.delete_uploaded_table(table_name)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["error"])

    invalidate_table_cache()
    return {"success": True, "message": result["message"], "table_name": table_name}


@app.get("/metrics")
async def get_metrics():
    """Return live cost and latency metrics for this server process."""
    return {
        "enabled": _METRICS_ENABLED,
        "costs": cost_tracker.summary() if cost_tracker else {},
        "latency": perf.all_stats() if perf else [],
    }


@app.options("/{path:path}")
async def options_handler(request: Request, path: str):
    return Response(status_code=204)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
