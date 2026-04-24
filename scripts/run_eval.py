"""
scripts/run_eval.py — Evaluation suite for the Decision System.

Covers three evaluation axes:
  1. eval_llms()         — Compare LLM models on RAG accuracy, SQL accuracy, latency
  2. eval_llm_rag_perf() — Compare RAG pipeline variants (pre/post-retrieval ablations)
  3. eval_llm_agentic()  — Measure agent routing correctness

Run:
    python -m scripts.run_eval
    # or to run a single section:
    python -m scripts.run_eval --mode llms
    python -m scripts.run_eval --mode rag
    python -m scripts.run_eval --mode agent
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
from observability.metrics.sys_perf import PerformanceTracker

# ── Config ────────────────────────────────────────────────────────────────────
RESULTS_DIR = ROOT / "eval_results"
RESULTS_DIR.mkdir(exist_ok=True)

_EMBED_DIR   = os.getenv("RAG_EMBED_DIR", "")
_EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "BAAI/bge-base-en-v1.5")

def _rag_paths() -> tuple[str, str]:
    key = _EMBED_MODEL.replace("/", "_").replace(".", "-")
    meta  = os.path.join(_EMBED_DIR, f"embeddings_{key}_meta_2.jsonl")
    faiss = os.path.join(_EMBED_DIR, f"embeddings_{key}_2.index")
    return meta, faiss

RAG_META, RAG_FAISS = _rag_paths()
RAG_READY = bool(_EMBED_DIR and os.path.exists(RAG_META))

# ── Test datasets ─────────────────────────────────────────────────────────────
RAG_TEST_CASES = [
    {
        "question": "What is the cure time for LOCTITE 401?",
        "keywords": ["cure", "time", "second", "minute"],
    },
    {
        "question": "What are the safety precautions when using adhesives?",
        "keywords": ["safety", "glove", "ventilation", "skin", "eye"],
    },
    {
        "question": "What is the viscosity of LOCTITE 401?",
        "keywords": ["viscosity", "cps", "mpa", "pa"],
    },
    {
        "question": "How do I apply LOCTITE adhesive properly?",
        "keywords": ["apply", "surface", "clean", "press", "hold"],
    },
    {
        "question": "What temperature range is LOCTITE 401 rated for?",
        "keywords": ["temperature", "°c", "°f", "range", "operating"],
    },
]

SQL_TEST_CASES = [
    {"question": "How many products are there in total?"},
    {"question": "Show me the top 5 products by sales revenue."},
    {"question": "What is the average deal size?"},
    {"question": "List all orders placed in the last 30 days."},
    {"question": "Which product has the highest number of units sold?"},
]

ROUTING_TEST_CASES = [
    {"question": "How many orders were placed last month?",                        "expected": "sql"},
    {"question": "Show me total revenue by product category.",                     "expected": "sql"},
    {"question": "What is the cure time for LOCTITE 401?",                         "expected": "rag"},
    {"question": "What are the safety precautions for this adhesive?",             "expected": "rag"},
    {"question": "Why did sales of LOCTITE 401 drop this quarter?",               "expected": "both"},
    {"question": "What are the specs of our best-selling product?",               "expected": "both"},
    {"question": "List the top 10 customers by revenue.",                          "expected": "sql"},
    {"question": "Explain the viscosity rating on the product datasheet.",         "expected": "rag"},
    {"question": "Compare the performance metrics with their technical specs.",    "expected": "both"},
    {"question": "How many units of each adhesive were sold last quarter?",       "expected": "sql"},
]

EVAL_MODELS = [m for m in LLM_MODELS if LLM_MODELS[m]["provider"] != "ollama"]

# ── Metric helpers ────────────────────────────────────────────────────────────

def _keyword_relevance(answer: str, keywords: list[str]) -> float:
    """Fraction of expected keywords present in the answer (case-insensitive)."""
    if not answer or not keywords:
        return 0.0
    a = answer.lower()
    return sum(1 for kw in keywords if kw.lower() in a) / len(keywords)


def _sql_success(question: str, data_service: DatabricksService, llm_model: str) -> tuple[bool, float]:
    """Return (success, latency_ms). Uses the agent SQL node end-to-end."""
    from backend.services.agent.tools.sql_tool import pick_table, get_columns, generate_sql_query, execute_sql_query
    try:
        t0 = time.perf_counter()
        table = pick_table(question, data_service, llm_model)
        columns = get_columns(table, data_service)
        sql = generate_sql_query(question, table, columns, llm_model=llm_model)
        result = execute_sql_query(sql, data_service)
        latency_ms = (time.perf_counter() - t0) * 1000
        return result.get("error") is None, latency_ms
    except Exception:
        return False, 0.0


# ── Charts ────────────────────────────────────────────────────────────────────

def print_chart(data: dict, title: str = "", ylabel: str = "Score") -> None:
    """
    Print a horizontal bar chart to stdout using ASCII, and save a PNG if
    matplotlib is available.

    data: {label: value}
    """
    if not data:
        print("  (no data)")
        return

    max_val = max(data.values()) or 1
    bar_width = 40
    print(f"\n  {title}")
    print("  " + "─" * (bar_width + 30))
    for label, val in sorted(data.items(), key=lambda x: -x[1]):
        filled = int(round((val / max_val) * bar_width))
        bar = "█" * filled + "░" * (bar_width - filled)
        print(f"  {label:<28} │{bar}│ {val:.3f}")
    print()

    try:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, max(3, len(data) * 0.6 + 1)))
        labels = list(data.keys())
        values = [data[l] for l in labels]
        bars = ax.barh(labels, values, color="#113D73", edgecolor="white")
        ax.bar_label(bars, fmt="%.3f", padding=4)
        ax.set_xlabel(ylabel)
        ax.set_title(title)
        ax.set_xlim(0, max_val * 1.15)
        fig.tight_layout()
        safe_title = title.replace(" ", "_").replace("/", "-")[:60]
        out = RESULTS_DIR / f"{safe_title}.png"
        fig.savefig(out, dpi=150)
        plt.close(fig)
        print(f"  Chart saved → {out}")
    except ImportError:
        pass  # matplotlib optional


# ── Save results ──────────────────────────────────────────────────────────────

def write_save_result(name: str, rows: list[dict]) -> Path:
    """Save evaluation rows to a timestamped CSV and JSON file."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path  = RESULTS_DIR / f"{name}_{ts}.csv"
    json_path = RESULTS_DIR / f"{name}_{ts}.json"

    if rows:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    with open(json_path, "w") as f:
        json.dump(rows, f, indent=2)

    print(f"  Results saved → {csv_path}")
    return csv_path


# ── Evaluation functions ──────────────────────────────────────────────────────

def eval_llms(models: Optional[list[str]] = None) -> None:
    """
    Evaluate each LLM on:
      - RAG answer relevance (keyword coverage)
      - Text2SQL execution accuracy
      - End-to-end latency
    """
    print("\n" + "═" * 60)
    print("  eval_llms — LLM comparison across RAG and Text2SQL")
    print("═" * 60)

    models = models or EVAL_MODELS
    data_service = DatabricksService()
    data_service.init_local_db()

    perf = PerformanceTracker()
    rows: list[dict] = []

    rag_scores: dict[str, float]  = {}
    sql_scores: dict[str, float]  = {}
    latency_map: dict[str, float] = {}

    for model in models:
        info = LLM_MODELS.get(model, {})
        req  = info.get("requires", "")
        if req and not os.getenv(req):
            print(f"  ⚠  Skipping {model} — {req} not set")
            continue

        print(f"\n  Model: {model}")
        rag_rel_total = 0.0
        sql_ok_total  = 0
        latencies: list[float] = []

        # RAG evaluation
        if RAG_READY:
            for tc in RAG_TEST_CASES:
                t0 = time.perf_counter()
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
                print(f"    RAG  [{relevance:.2f}] {tc['question'][:55]}")
            rag_score = rag_rel_total / len(RAG_TEST_CASES)
        else:
            print("    RAG  skipped (embeddings not configured)")
            rag_score = 0.0

        # SQL evaluation
        for tc in SQL_TEST_CASES:
            ok, lat = _sql_success(tc["question"], data_service, model)
            if lat > 0:
                latencies.append(lat)
            sql_ok_total += int(ok)
            print(f"    SQL  [{'✓' if ok else '✗'}] {tc['question'][:55]}")

        sql_score = sql_ok_total / len(SQL_TEST_CASES)
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        rag_scores[model]   = round(rag_score, 3)
        sql_scores[model]   = round(sql_score, 3)
        latency_map[model]  = round(avg_latency, 1)

        rows.append({
            "model":           model,
            "rag_relevance":   round(rag_score, 3),
            "sql_accuracy":    round(sql_score, 3),
            "avg_latency_ms":  round(avg_latency, 1),
        })

    print_chart(rag_scores,  title="RAG Answer Relevance by Model",    ylabel="Keyword Coverage")
    print_chart(sql_scores,  title="Text2SQL Execution Accuracy by Model", ylabel="Accuracy")
    print_chart(latency_map, title="Average Latency by Model (ms)",    ylabel="ms")
    write_save_result("eval_llms", rows)


def eval_llm_rag_perf(model: str = "gemini-2.5-flash") -> None:
    """
    Ablation study on the RAG pipeline:
      - vanilla:        no query expansion, no reranker
      - pre_retrieval:  query expansion only
      - post_retrieval: reranker only
      - full:           query expansion + reranker
    """
    print("\n" + "═" * 60)
    print("  eval_llm_rag_perf — RAG pipeline ablation")
    print("═" * 60)

    if not RAG_READY:
        print("  ⚠  RAG embeddings not configured — skipping")
        return

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
                prompt  = build_prompt(context=context, question=tc["question"])
                answer  = ask_llm(prompt, llm_origin="Gemini", llm_model=model)
                latency_ms = (time.perf_counter() - t0) * 1000

                relevance = _keyword_relevance(answer, tc["keywords"])
                relevance_total += relevance
                latencies.append(latency_ms)
                print(f"    [{relevance:.2f}] {tc['question'][:55]}")
            except Exception as e:
                print(f"    [ERR] {tc['question'][:55]} — {e}")
                latencies.append(0.0)

        avg_relevance = relevance_total / len(RAG_TEST_CASES)
        avg_latency   = sum(latencies) / len(latencies) if latencies else 0.0

        answer_relevance[variant] = round(avg_relevance, 3)
        latency_map[variant]      = round(avg_latency, 1)

        rows.append({
            "variant":         variant,
            "use_expansion":   cfg["use_expansion"],
            "use_reranker":    cfg["use_reranker"],
            "answer_relevance":round(avg_relevance, 3),
            "avg_latency_ms":  round(avg_latency, 1),
        })

    print_chart(answer_relevance, title="RAG Answer Relevance by Pipeline Variant", ylabel="Keyword Coverage")
    print_chart(latency_map,      title="RAG Latency by Pipeline Variant (ms)",     ylabel="ms")
    write_save_result("eval_rag_perf", rows)


def eval_llm_agentic(model: str = "gemini-2.5-flash") -> None:
    """
    Measure routing correctness: does the router send questions to the
    right pipeline (sql / rag / both)?
    """
    print("\n" + "═" * 60)
    print("  eval_llm_agentic — agent routing correctness")
    print("═" * 60)

    rows: list[dict] = []
    correct = 0
    per_route: dict[str, dict] = {"sql": {"correct": 0, "total": 0},
                                   "rag": {"correct": 0, "total": 0},
                                   "both": {"correct": 0, "total": 0}}

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
        expected  = tc["expected"]
        ok        = predicted == expected
        correct  += int(ok)

        per_route[expected]["total"]   += 1
        per_route[expected]["correct"] += int(ok)

        status = "✓" if ok else f"✗ (got {predicted})"
        print(f"  [{status:<14}] expected={expected:<4} | {tc['question'][:55]}")

        rows.append({
            "question":     tc["question"],
            "expected":     expected,
            "predicted":    predicted,
            "correct":      ok,
            "latency_ms":   round(latency_ms, 1),
            "reasoning":    result.get("route_reasoning", ""),
        })

    overall_acc = correct / len(ROUTING_TEST_CASES)
    route_acc = {
        route: round(v["correct"] / v["total"], 3) if v["total"] > 0 else 0.0
        for route, v in per_route.items()
    }
    route_acc["overall"] = round(overall_acc, 3)

    print(f"\n  Overall routing accuracy: {correct}/{len(ROUTING_TEST_CASES)} = {overall_acc:.1%}")
    print_chart(route_acc, title=f"Routing Accuracy by Category (model={model})", ylabel="Accuracy")
    write_save_result("eval_agentic", rows)


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
        help="Model to use for RAG and agent evals (default: gemini-2.5-flash)",
    )
    args = parser.parse_args()

    print(f"\n{'═' * 60}")
    print(f"  Decision System Evaluation  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Results will be saved to: {RESULTS_DIR}")
    print(f"{'═' * 60}")

    if args.mode in ("llms", "all"):
        eval_llms()

    if args.mode in ("rag", "all"):
        eval_llm_rag_perf(model=args.model)

    if args.mode in ("agent", "all"):
        eval_llm_agentic(model=args.model)

    print("\n  Done.\n")


if __name__ == "__main__":
    main()
