"""
tracing.py — LangSmith tracing for the RAG and Text-to-SQL pipelines.

Each pipeline stage is wrapped with @traceable so that every call appears
in the LangSmith UI as a structured run tree.  Both RAGTracer and
Text2SQLTracer expose a `query_and_share()` method that returns
  {"answer": ..., "trace_url": ...}
so the FastAPI endpoints can pass the trace URL back to the frontend.


Usage
-----
    from observability.tracing import RAGTracer, Text2SQLTracer

    rag = RAGTracer(metadata_path=..., faiss_path=..., ...)
    result = rag.query_and_share("What is the cure time for LOCTITE 454?")
    # result == {"answer": "...", "trace_url": "https://smith.langchain.com/public/..."}

    sql = Text2SQLTracer()
    result = sql.query_and_share("Show top 10 sales", table_name="sales")
    # result == {"sql": "SELECT ...", "trace_url": "..."}
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Optional

from langsmith import traceable, Client
from langsmith.run_helpers import get_current_run_tree


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def configure_langsmith(
    api_key: Optional[str] = None,
    project: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> None:
    """
    Set LangSmith environment variables programmatically.

    Call this before any traced functions if you are not relying solely on
    environment variables set before process start.
    """
    os.environ["LANGCHAIN_TRACING_V2"] = "true"

    if api_key:
        os.environ["LANGCHAIN_API_KEY"] = api_key
    if project:
        os.environ["LANGCHAIN_PROJECT"] = project
    if endpoint:
        os.environ["LANGCHAIN_ENDPOINT"] = endpoint

    if not os.environ.get("LANGCHAIN_API_KEY"):
        raise EnvironmentError(
            "LANGCHAIN_API_KEY is not set. "
            "Pass api_key= or set the LANGCHAIN_API_KEY environment variable."
        )

    print(
        f"LangSmith tracing enabled — project: "
        f"{os.environ.get('LANGCHAIN_PROJECT', 'default')}"
    )


def get_client() -> Client:
    """Return a LangSmith Client using the current environment configuration."""
    return Client()


def _share_run(run_id: str) -> Optional[str]:
    """
    Create a public shareable LangSmith URL for *run_id*.

    Returns None if sharing fails (e.g. tracing is disabled or API key is wrong).
    """
    try:
        return get_client().share_run(run_id)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# RAG stage-level traced functions
# ---------------------------------------------------------------------------

@traceable(run_type="chain", name="query-preparation")
def trace_query_preparation(
    query: str,
    *,
    expander,
) -> dict[str, Any]:
    """Normalize, rewrite, and expand the raw query."""
    prepared = expander.expand(query)
    return {
        "original": prepared.original,
        "rewritten": prepared.rewritten,
        "expansions": prepared.expansions,
        "all_queries": prepared.all_queries(),
    }


@traceable(run_type="retriever", name="hybrid-retrieval")
def trace_retrieval(
    query: str,
    *,
    retriever,
    initial_k: int = 10,
    final_k: int = 5,
    product_uuid: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Run hybrid retrieval and return serialisable results."""
    results = retriever.retrieve(
        query,
        initial_k=initial_k,
        final_k=final_k,
        product_uuid=product_uuid,
    )
    return [
        {"text": r.text, "score": r.score, "source": r.source, "metadata": r.metadata}
        for r in results
    ]


@traceable(run_type="retriever", name="prepared-query-retrieval")
def trace_retrieval_prepared(
    prepared_query,
    *,
    retriever,
    initial_k: int = 10,
    final_k: int = 5,
    product_uuid: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Run retrieval across all query variants from a PreparedQuery."""
    results = retriever.retrieve_for_prepared_query(
        prepared_query,
        initial_k=initial_k,
        final_k=final_k,
        product_uuid=product_uuid,
    )
    return [
        {"text": r.text, "score": r.score, "source": r.source, "metadata": r.metadata}
        for r in results
    ]


@traceable(run_type="chain", name="prompt-construction")
def trace_build_prompt(
    context: str,
    question: str,
    history: Optional[list[dict]] = None,
) -> str:
    """Build the RAG prompt and log both inputs and the assembled string."""
    from services.rag.generation.generation_o import build_prompt
    return build_prompt(context=context, question=question, history=history)


@traceable(run_type="llm", name="llm-generation")
def trace_generation(
    prompt: str,
    *,
    llm_origin: str = "Gemini",
    llm_model: str = "gemini-2.5-flash",
    temperature: float = 0.2,
    max_tokens: int = 2048,
    base_url: Optional[str] = None,
    use_vllm: bool = False,
) -> str:
    """Call the LLM and trace the full prompt → response."""
    from services.rag.generation.generation_o import ask_llm
    return ask_llm(
        prompt,
        llm_origin=llm_origin,
        llm_model=llm_model,
        temperature=temperature,
        max_tokens=max_tokens,
        base_url=base_url,
        use_vllm=use_vllm,
    )


# ---------------------------------------------------------------------------
# Text-to-SQL stage-level traced functions
# ---------------------------------------------------------------------------

@traceable(run_type="chain", name="sql-generation")
def trace_sql_generation(
    question: str,
    *,
    table_name: str,
    columns_list: Optional[list[str]] = None,
    custom_limit: Optional[int] = None,
    llm_model: str = "gemini-2.5-flash",
) -> str:
    """Generate SQL from a natural-language question and log the prompt+output."""
    from services.text2sql.generation.sql_generation import generate_sql
    return generate_sql(
        question=question,
        table_name=table_name,
        columns_list=columns_list,
        custom_limit=custom_limit,
        llm_model=llm_model,
    )


@traceable(run_type="chain", name="dataset-size-detection")
def trace_detect_large_dataset(question: str) -> dict[str, Any]:
    """Detect whether the user is asking for a large result set."""
    from services.text2sql.generation.sql_generation import detect_large_dataset_request
    is_large, custom_limit, timeout = detect_large_dataset_request(question)
    return {"is_large": is_large, "custom_limit": custom_limit, "timeout": timeout}


# ---------------------------------------------------------------------------
# End-to-end RAGTracer
# ---------------------------------------------------------------------------

class RAGTracer:
    """
    Full RAG pipeline with LangSmith tracing.

    Call .query_and_share() from your API endpoint to get back both the
    answer and a public LangSmith trace URL to send to the frontend.
    """

    def __init__(
        self,
        metadata_path: str,
        faiss_path: str,
        embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        llm_origin: str = "Gemini",
        llm_model: str = "gemini-2.5-flash",
        reranker_model_name: Optional[str] = None,
        trust_remote_code: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        base_url: Optional[str] = None,
        use_vllm: bool = False,
        initial_k: int = 10,
        final_k: int = 5,
        langsmith_project: Optional[str] = None,
        langsmith_api_key: Optional[str] = None,
    ) -> None:
        configure_langsmith(api_key=langsmith_api_key, project=langsmith_project)

        from services.rag.retrieval.hybrid_retriever import HybridRetriever
        from services.rag.pre_retrieval.query_expansion import QueryExpander

        self.retriever = HybridRetriever(
            metadata_path=metadata_path,
            faiss_path=faiss_path,
            embed_model_name=embed_model_name,
            reranker_model_name=reranker_model_name,
            trust_remote_code=trust_remote_code,
        )
        self.expander = QueryExpander()
        self.llm_origin = llm_origin
        self.llm_model = llm_model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.base_url = base_url
        self.use_vllm = use_vllm
        self.initial_k = initial_k
        self.final_k = final_k

    @traceable(run_type="chain", name="rag-query")
    def query(
        self,
        question: str,
        history: Optional[list[dict]] = None,
        product_uuid: Optional[str] = None,
    ) -> str:
        """
        Run the full RAG pipeline and return the answer.

        Captures the run_id on self so query_and_share() can share it
        after this call returns.
        """
        run_tree = get_current_run_tree()
        self._last_run_id = str(run_tree.id) if run_tree else None

        prepared = self.expander.expand(question)
        trace_query_preparation(question, expander=self.expander)

        raw_results = trace_retrieval_prepared(
            prepared,
            retriever=self.retriever,
            initial_k=self.initial_k,
            final_k=self.final_k,
            product_uuid=product_uuid,
        )

        context = "\n\n".join(r["text"] for r in raw_results)
        prompt = trace_build_prompt(context, question, history=history)

        return trace_generation(
            prompt,
            llm_origin=self.llm_origin,
            llm_model=self.llm_model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            base_url=self.base_url,
            use_vllm=self.use_vllm,
        )

    def query_and_share(
        self,
        question: str,
        history: Optional[list[dict]] = None,
        product_uuid: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Run the RAG pipeline and return the answer + a shareable LangSmith URL.

        Use this in your FastAPI endpoints:
            result = rag_tracer.query_and_share(body.question, history=history)
            return {"answer": result["answer"], "trace_url": result["trace_url"]}
        """
        self._last_run_id = None
        answer = self.query(question, history=history, product_uuid=product_uuid)
        trace_url = _share_run(self._last_run_id) if self._last_run_id else None
        return {"answer": answer, "trace_url": trace_url}


# ---------------------------------------------------------------------------
# End-to-end Text2SQLTracer
# ---------------------------------------------------------------------------

class Text2SQLTracer:
    """
    Text-to-SQL pipeline with LangSmith tracing.

    Call .query_and_share() from your API endpoint to get back the generated
    SQL, result metadata, and a public LangSmith trace URL.
    """

    def __init__(
        self,
        langsmith_project: Optional[str] = None,
        langsmith_api_key: Optional[str] = None,
    ) -> None:
        configure_langsmith(api_key=langsmith_api_key, project=langsmith_project)
        self._last_run_id: Optional[str] = None

    @traceable(run_type="chain", name="text2sql-query")
    def query(
        self,
        question: str,
        table_name: str,
        columns_list: Optional[list[str]] = None,
        llm_model: str = "gemini-2.5-flash",
    ) -> dict[str, Any]:
        """
        Detect dataset size, generate SQL, and return a dict with the results.

        Captures the run_id so query_and_share() can attach a trace URL.
        """
        run_tree = get_current_run_tree()
        self._last_run_id = str(run_tree.id) if run_tree else None

        size_info = trace_detect_large_dataset(question)
        sql = trace_sql_generation(
            question,
            table_name=table_name,
            columns_list=columns_list,
            custom_limit=size_info["custom_limit"],
            llm_model=llm_model,
        )

        return {
            "sql": sql,
            "is_large_dataset": size_info["is_large"],
            "custom_limit": size_info["custom_limit"],
            "recommended_timeout": size_info["timeout"],
        }

    def query_and_share(
        self,
        question: str,
        table_name: str,
        columns_list: Optional[list[str]] = None,
        llm_model: str = "gemini-2.5-flash",
    ) -> dict[str, Any]:
        """
        Run Text-to-SQL and return generated SQL + a shareable LangSmith URL.

        Use this in your FastAPI endpoints:
            result = sql_tracer.query_and_share(body.question, table_name=...)
            return {"sql_query": result["sql"], "trace_url": result["trace_url"]}
        """
        self._last_run_id = None
        result = self.query(question, table_name, columns_list=columns_list, llm_model=llm_model)
        trace_url = _share_run(self._last_run_id) if self._last_run_id else None
        return {**result, "trace_url": trace_url}
