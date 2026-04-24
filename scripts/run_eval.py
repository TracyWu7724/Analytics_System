"""
scripts/run_eval.py — Evaluation suite for the Decision System.

Covers three evaluation axes:
  1. eval_llms()         — Compare LLM models on RAG accuracy, SQL accuracy, latency
  2. eval_llm_rag_perf() — Compare RAG pipeline variants (pre/post-retrieval ablations)
  3. eval_llm_agentic()  — Measure agent routing correctness

Run from the repo root:
    python -m scripts.run_eval                          # all evals, gemini-2.5-flash
    python -m scripts.run_eval --mode agent --model gpt-4o
    python -m scripts.run_eval --mode llms
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# ── Imports ───────────────────────────────────────────────────────────────────
from backend.services.agent.tools.rag_tool import run_rag
from backend.services.agent.nodes.router import router_node
from backend.services.text2sql.db.databricks_service import DatabricksService
from backend.services.text2sql.generation.llm_registry import LLM_MODELS

# ── Directories ───────────────────────────────────────────────────────────────
RESULTS_DIR = ROOT / "eval" / "eval_result"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ── RAG config from env ───────────────────────────────────────────────────────
_EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
_RERANKER_MODEL = os.getenv("RAG_RERANKER_MODEL", None)
_EMBED_DIR = os.getenv("RAG_EMBED_DIR", "")


def _rag_paths(embed_model: str, embed_dir: str) -> tuple[str, str]:
    key = embed_model.replace("/", "_").replace(".", "-")
    meta = os.path.join(embed_dir, f"embeddings_{key}_meta_2.jsonl")
    faiss = os.path.join(embed_dir, f"embeddings_{key}_2.index")
    return meta, faiss


RAG_META, RAG_FAISS = _rag_paths(_EMBED_MODEL, _EMBED_DIR) if _EMBED_DIR else ("", "")
RAG_READY = bool(_EMBED_DIR and os.path.exists(RAG_META))

# ── Models to evaluate ────────────────────────────────────────────────────────
# Only include models whose API key is available
def _available_models() -> list[str]:
    available = []
    for model, info in LLM_MODELS.items():
        req = info.get("requires", "")
        provider = info.get("provider", "")
        if provider == "ollama":
            continue  # skip local models in eval by default
        if not req or os.getenv(req):
            available.append(model)
    return available

EVAL_MODELS = _available_models()

# ── Test cases ────────────────────────────────────────────────────────────────

RAG_TEST_CASES = [
    {
        "question": "If I want adhesives weaker than LOCTITE 271, what is the product recommendation?",
        "keywords": ["LOCTITE 243", "medium strength", "threadlocking"],
    },
    {
        "question": "What scenario is Loctite 401 suited for?",
        "keywords": ["instant adhesive", "metals", "plastics", "elastomers"],
    },
    {
        "question": "Can you recommend a medium strength threadlocking adhesive bestseller?",
        "keywords": ["LOCTITE 243"],
    },
    {
        "question": "What scenario is Loctite 567 suited for?",
        "keywords": ["tapered threads", "fittings", "leakage", "vibration"],
    },
    {
        "question": "What is the cure time for LOCTITE 401?",
        "keywords": ["cure", "fixturing", "second", "minute"],
    },
]

SQL_TEST_CASES = [
    {"question": "How many rows are in the database?"},
    {"question": "Show me the top 5 products by sales volume"},
    {"question": "What are the available tables?"},
    {"question": "List the most recent orders"},
    {"question": "What is the total revenue this year?"},
]

ROUTING_TEST_CASES = [
    {"question": "How many units of LOCTITE 401 were sold last quarter?",           "expected": "sql"},
    {"question": "Show me the top 10 products by revenue",                           "expected": "sql"},
    {"question": "What are the total sales figures for this year?",                  "expected": "sql"},
    {"question": "List all orders placed in January",                                "expected": "sql"},
    {"question": "What is the cure time for LOCTITE 401?",                           "expected": "rag"},
    {"question": "What are the safety precautions for LOCTITE 243?",                 "expected": "rag"},
    {"question": "Explain the viscosity specs of LOCTITE 567",                       "expected": "rag"},
    {"question": "How do I apply this adhesive?",                                    "expected": "rag"},
    {"question": "Why did sales of LOCTITE 401 drop this quarter?",                  "expected": "both"},
    {"question": "What are the specs of our best-selling adhesive product?",         "expected": "both"},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _keyword_relevance(answer: str, keywords: list[str]) -> float:
    """Fraction of expected keywords present in the answer (case-insensitive)."""
    if not answer or not keywords:
        return 0.0
    a = answer.lower()
    return sum(1 for kw in keywords if kw.lower() in a) / len(keywords)


def _sql_success(question: str, data_service: DatabricksService, llm_model: str) -> tuple[bool, float]:
    """Return (success, latency_ms). Runs the full SQL pipeline end-to-end."""
    from backend.services.agent.tools.sql_tool import (
        pick_table, get_columns, generate_sql_query, execute_sql_query,
    )
    try:
        t0 = time.perf_counter()
        table = pick_table(question, data_service, uploaded_table=None)
        columns = get_columns(table, data_service)
        sql = generate_sql_query(question, table, columns, llm_model=llm_model)
        rows = execute_sql_query(sql, table, data_service)
        latency_ms = (time.perf_counter() - t0) * 1000
        return True, latency_ms
    except Exception as exc:
        print(f"      SQL error: {exc}")
        return False, 0.0


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_result(name: str, rows: list[dict], summary: dict | None = None) -> Path:
    """Save evaluation rows to a timestamped JSON (and CSV) file, plus update summary.json."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = RESULTS_DIR / f"{name}_{ts}.json"
    csv_path  = RESULTS_DIR / f"{name}_{ts}.csv"

    payload = {"name": name, "timestamp": ts, "rows": rows}
    if summary:
        payload["summary"] = summary

    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)

    if rows:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    print(f"  Results saved → {json_path}")
    return json_path


def _update_latest(all_results: dict) -> None:
    """Write / overwrite eval/eval_result/latest.json with the full run summary."""
    path = RESULTS_DIR / "latest.json"
    with open(path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"  Summary saved → {path}")


# ── Eval functions ────────────────────────────────────────────────────────────

def eval_llms(models: Optional[list[str]] = None) -> dict:
    """Evaluate each LLM on RAG relevance, SQL accuracy, and latency."""
    print("\n" + "═" * 60)
    print("  eval_llms — LLM comparison across RAG and Text2SQL")
    print("═" * 60)

    models = models or EVAL_MODELS
    data_service = DatabricksService()
    data_service.init_local_db()

    rows: list[dict] = []
    rag_scores: dict[str, float] = {}
    sql_scores: dict[str, float] = {}
    latency_map: dict[str, float] = {}

    for model in models:
        info = LLM_MODELS.get(model, {})
        req = info.get("requires", "")
        if req and not os.getenv(req):
            print(f"  Skipping {model} — {req} not set")
            continue

        print(f"\n  Model: {model}")
        rag_rel_total = 0.0
        sql_ok_total = 0
        latencies: list[float] = []

        # RAG evaluation
        if RAG_READY:
            for tc in RAG_TEST_CASES:
                t0 = time.perf_counter()
                try:
                    result = run_rag(
                        question=tc["question"],
                        metadata_path=RAG_META,
                        faiss_path=RAG_FAISS,
                        embed_model_name=_EMBED_MODEL,
                        llm_model=model,
                    )
                    latency_ms = (time.perf_counter() - t0) * 1000
                    latencies.append(latency_ms)
                    relevance = _keyword_relevance(result.get("answer", ""), tc["keywords"])
                    rag_rel_total += relevance
                    print(f"    RAG [{relevance:.2f}] {tc['question'][:55]}")
                except Exception as e:
                    print(f"    RAG [ERR] {tc['question'][:55]} — {e}")
            rag_score = rag_rel_total / len(RAG_TEST_CASES)
        else:
            print("    RAG skipped (embeddings not configured)")
            rag_score = 0.0

        # SQL evaluation
        for tc in SQL_TEST_CASES:
            ok, lat = _sql_success(tc["question"], data_service, model)
            if lat > 0:
                latencies.append(lat)
            sql_ok_total += int(ok)
            print(f"    SQL [{'OK' if ok else 'FAIL'}] {tc['question'][:55]}")

        sql_score = sql_ok_total / len(SQL_TEST_CASES)
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        rag_scores[model] = round(rag_score, 3)
        sql_scores[model] = round(sql_score, 3)
        latency_map[model] = round(avg_latency, 1)

        rows.append({
            "model": model,
            "rag_relevance": round(rag_score, 3),
            "sql_accuracy": round(sql_score, 3),
            "avg_latency_ms": round(avg_latency, 1),
        })

    summary = {
        "rag_relevance": rag_scores,
        "sql_accuracy": sql_scores,
        "avg_latency_ms": latency_map,
    }
    _save_result("eval_llms", rows, summary)
    return summary


def eval_llm_rag_perf(model: str = "gemini-2.5-flash") -> dict:
    """
    Ablation study on the RAG pipeline:
      vanilla / pre_retrieval / post_retrieval / full_pipeline
    """
    print("\n" + "═" * 60)
    print("  eval_llm_rag_perf — RAG pipeline ablation")
    print("═" * 60)

    if not RAG_READY:
        print("  RAG embeddings not configured — skipping")
        return {}

    from backend.services.rag.retrieval.hybrid_retriever import HybridRetriever
    from backend.services.rag.pre_retrieval.query_expansion import QueryExpander
    from backend.services.rag.generation.generation import ask_llm, build_prompt

    configs = {
        "vanilla":        {"use_expansion": False, "use_reranker": False},
        "pre_retrieval":  {"use_expansion": True,  "use_reranker": False},
        "post_retrieval": {"use_expansion": False, "use_reranker": True},
        "full_pipeline":  {"use_expansion": True,  "use_reranker": True},
    }

    rows: list[dict] = []
    answer_relevance: dict[str, float] = {}
    latency_map: dict[str, float] = {}

    for variant, cfg in configs.items():
        print(f"\n  Variant: {variant}")
        relevance_total = 0.0
        latencies: list[float] = []

        retriever = HybridRetriever(
            metadata_path=RAG_META,
            faiss_path=RAG_FAISS,
            embed_model_name=_EMBED_MODEL,
            reranker_model_name=os.getenv("RAG_RERANKER_MODEL") if cfg["use_reranker"] else None,
        )
        expander = QueryExpander() if cfg["use_expansion"] else None

        for tc in RAG_TEST_CASES:
            t0 = time.perf_counter()
            try:
                if expander:
                    prepared = expander.expand(tc["question"])
                    results = retriever.retrieve_for_prepared_query(prepared, initial_k=10, final_k=5)
                else:
                    results = retriever.retrieve(tc["question"], initial_k=10, final_k=5)

                context = "\n\n".join(r.text for r in results)
                prompt = build_prompt(context=context, question=tc["question"])
                answer = ask_llm(prompt, llm_origin="Gemini", llm_model=model)
                latency_ms = (time.perf_counter() - t0) * 1000

                relevance = _keyword_relevance(answer, tc["keywords"])
                relevance_total += relevance
                latencies.append(latency_ms)
                print(f"    [{relevance:.2f}] {tc['question'][:55]}")
            except Exception as e:
                print(f"    [ERR] {tc['question'][:55]} — {e}")
                latencies.append(0.0)

        avg_relevance = relevance_total / len(RAG_TEST_CASES)
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        answer_relevance[variant] = round(avg_relevance, 3)
        latency_map[variant] = round(avg_latency, 1)

        rows.append({
            "variant": variant,
            "use_expansion": cfg["use_expansion"],
            "use_reranker": cfg["use_reranker"],
            "answer_relevance": round(avg_relevance, 3),
            "avg_latency_ms": round(avg_latency, 1),
        })

    summary = {"answer_relevance": answer_relevance, "avg_latency_ms": latency_map}
    _save_result("eval_rag_perf", rows, summary)
    return summary


def eval_llm_agentic(model: str = "gemini-2.5-flash") -> dict:
    """Measure routing correctness."""
    print("\n" + "═" * 60)
    print("  eval_llm_agentic — agent routing correctness")
    print("═" * 60)

    rows: list[dict] = []
    correct = 0
    per_route: dict[str, dict] = {
        "sql":  {"correct": 0, "total": 0},
        "rag":  {"correct": 0, "total": 0},
        "both": {"correct": 0, "total": 0},
    }

    for tc in ROUTING_TEST_CASES:
        state = {
            "question": tc["question"],
            "llm_model": model,
            "history": [],
            "uploaded_table": None,
        }
        t0 = time.perf_counter()
        result = router_node(state)
        latency_ms = (time.perf_counter() - t0) * 1000

        predicted = result.get("route", "sql")
        expected = tc["expected"]
        ok = predicted == expected
        correct += int(ok)

        per_route[expected]["total"] += 1
        per_route[expected]["correct"] += int(ok)

        status = "OK" if ok else f"FAIL (got {predicted})"
        print(f"  [{status:<18}] expected={expected:<4} | {tc['question'][:55]}")

        rows.append({
            "question":   tc["question"],
            "expected":   expected,
            "predicted":  predicted,
            "correct":    ok,
            "latency_ms": round(latency_ms, 1),
            "reasoning":  result.get("route_reasoning", ""),
        })

    overall_acc = correct / len(ROUTING_TEST_CASES)
    route_acc = {
        route: round(v["correct"] / v["total"], 3) if v["total"] > 0 else 0.0
        for route, v in per_route.items()
    }
    route_acc["overall"] = round(overall_acc, 3)

    print(f"\n  Overall routing accuracy: {correct}/{len(ROUTING_TEST_CASES)} = {overall_acc:.1%}")

    summary = {"routing_accuracy": route_acc}
    _save_result("eval_agentic", rows, summary)
    return summary


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Decision System evaluation suite")
    parser.add_argument(
        "--mode",
        choices=["llms", "rag", "agent", "all"],
        default="all",
        help="Which evaluation to run (default: all)",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Model to use for RAG-perf and agent evals (default: gemini-2.5-flash)",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        help="Explicit list of models for eval_llms (overrides auto-detection)",
    )
    args = parser.parse_args()

    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'═' * 60}")
    print(f"  Decision System Evaluation  —  {run_ts}")
    print(f"  Mode: {args.mode}   Model: {args.model}")
    print(f"  Results → {RESULTS_DIR}")
    print(f"{'═' * 60}")

    all_results: dict = {
        "timestamp": run_ts,
        "mode": args.mode,
        "model": args.model,
    }

    if args.mode in ("llms", "all"):
        models = args.models or None
        all_results["eval_llms"] = eval_llms(models)

    if args.mode in ("rag", "all"):
        all_results["eval_rag_perf"] = eval_llm_rag_perf(model=args.model)

    if args.mode in ("agent", "all"):
        all_results["eval_agentic"] = eval_llm_agentic(model=args.model)

    _update_latest(all_results)
    print("\n  Done.\n")


if __name__ == "__main__":
    main()
