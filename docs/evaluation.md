# Evaluation

How Text2SQL, RAG, and the router are measured — datasets, metrics,
pipeline, and the latest benchmark results in `assets/`.

## Datasets

All datasets live in `eval/dataset/`:

| File | Rows | Purpose |
|---|---|---|
| `text2sql_eval.csv` | 24 | Text2SQL correctness + guardrail coverage. Columns: `question`, `sql` (reference), `expected_answer`, `type`, `expected_failure_mode`, `should_trigger_guardrail`, `guardrail_layer`, `confidence_score_expected`. `type` spans `normal`, `edge_case`, `multi_hop`, `hallucination_schema`, `hallucination_value`, `unsupported_task` — i.e. it deliberately includes adversarial cases designed to trip the hallucination guard, not just happy-path questions. |
| `routing_eval.csv` | 59 | Router accuracy. Columns: `question`, `expected_mode` (`RAG` \| `Text2SQL` \| `Text2SQL + RAG`), `answerable`. |
| `rag_eval.csv` | 99 | The richest RAG benchmark: `query_type`, `expected_products`, `expected_category`, `expected_evidence_facts`, `hard_negative_products` (distractor products that should *not* be retrieved), `answerable`, `expected_refusal_or_guardrail`, `difficulty`, plus columns naming which metrics apply to each row (`retrieval_metrics_to_check`, `answer_metrics_to_check`, `grounding_metrics_to_check`, `robustness_metrics_to_check`). |
| `rag_test_data.csv` | 22 | Smaller RAG set with binary `relevance_label` / `Henkel_label` annotations. |
| `rag_test_data_henkel_small.csv` | 102 | `generated_answer` vs `expected_answer` vs `expected_product` — a pre-generated answer comparison set (answers already produced, not run live). |
| `rag_generation_qualiy_eval.csv` | 4 | Tiny spot-check set of `query`/`answer` pairs. |

**Note:** `rag_eval.csv`'s metric-name columns (`Recall@3`, `NDCG@5`,
`citation_support`, `hallucination_flag`, `grounded_refusal_accuracy`, …)
describe an intended evaluation design richer than what's currently
implemented in `eval/metrics/` (see [Known gaps](#known-gaps) below) — the
CSV is annotated ahead of the metric code that would fully consume it.

## Metrics

`eval/metrics/` implements two metric families, both as `deepeval`
`BaseMetric` subclasses (`measure()` / `a_measure()`) so they plug into the
`deepeval` CLI/test-case flow used elsewhere in the codebase (`.deepeval`
config, `LLMTestCase`).

**RAG metrics** (score every retrieved-chunk-and-answer pair):

| Metric | File | Formula |
|---|---|---|
| Accuracy | `accuracy.py` | Exact match → 1.0; else token-F1(actual, expected); else optional LLM semantic judge (gemini-2.5-flash) if F1 is 0 |
| Faithfulness | `faithfulness.py` | Fraction of content words (stop-words excluded) in the answer that appear in the retrieved chunks — "is the answer grounded in what was retrieved?" |
| Answer relevancy | `answer_relevancy.py` | Token-overlap precision of actual vs. expected answer |
| Contextual precision | `context_precision.py` | Weighted precision@k over the retrieved chunk ranking — rewards relevant chunks ranked near the top |
| Contextual recall | `context_recall.py` | `|retrieved ∩ ideal| / |ideal|` — did retrieval find the reference chunks? |
| Contextual relevancy | `context_relevancy.py` | `|retrieved ∩ ideal| / |retrieved|` — how much of what came back was actually relevant? |

These are simplified, dependency-free adaptations of WrenAI's SQL-execution-based
metrics — since there's no SQL/engine step in RAG, each docstring explains
the substitution made (e.g. Faithfulness there compares SQL columns to
retrieved schema; here it compares answer tokens to retrieved chunk text).

**Text2SQL metrics** (`text2sql_metrics.py`, 8 metrics via `Text2SQLResult`
+ `evaluate_text2sql()`):

| Metric | What it catches |
|---|---|
| `TableRoutingMetric` | Wrong table picked (suffix match against `expected_table`) |
| `ColumnRoutingMetric` | Fraction of expected columns actually referenced in the generated SQL |
| `SQLValidationRateMetric` | 1.0 first-attempt pass, 0.5 passed after self-correction, 0.0 never passed — measures how often the guard's retry loop had to intervene |
| `ExecutionAccuracyMetric` | 1.0 ran + non-empty, 0.5 ran + empty, 0.0 execution error |
| `EmptyResultFPMetric` | SQL returned 0 rows but the final answer still claims data exists (a specific hallucination shape) |
| `SchemaHallucinationMetric` | SQL referencing non-existent columns/tables |
| `AnswerFaithfulnessMetric` | Numbers cited in the NL answer must appear in the actual SQL result rows |
| `GuardrailEffectivenessMetric` | For rows where `should_trigger_guardrail=True`, did the guard actually fire? (true-positive rate, not just accuracy) |

## Evaluation pipeline

```
eval/dataset/*.csv  ──►  run the live agent/pipeline per row
                            (sql_node / rag_node / router_node directly,
                             or via the /agent/query API)
                    ──►  populate Text2SQLResult / LLMTestCase objects
                    ──►  eval/metrics/*.py  scores each case
                    ──►  aggregate()  →  summary dict per metric
                    ──►  assets/*.png  (bar charts vs. an 80% threshold line)
```

`evaluate_text2sql()` is the single entry point for the Text2SQL side —
pass it a list of populated `Text2SQLResult` objects and it runs all 8
metrics and returns one summary dict. The RAG metrics are consumed
individually as `deepeval` `BaseMetric` instances against `LLMTestCase`s
built from `rag_eval.csv` rows.

**Gap:** the script that actually drove the CSVs through the live pipeline
and produced the `assets/*.png` charts is not present in this repo —
`scripts/run_eval.py` existed at some point (an orphaned compiled
`run_eval.cpython-314.pyc` with no matching source was found and removed
during a repo cleanup) but the source itself is gone. Re-running the
benchmarks today means re-writing that driver: iterate a CSV, call the
agent/pipeline for each row, populate the result dataclasses, and call the
metrics above.

## Offline evaluation

All of the above — datasets + metrics — run offline, against a fixed CSV
and (for Text2SQL) a fixed reference SQL/answer, independent of live
traffic. This is the only evaluation currently backed by the
`assets/*.png` benchmark charts (see below).

## Online evaluation

Production traffic feeds two lightweight, always-on signals — no offline
dataset involved:

1. **User feedback** — `POST /feedback` (thumbs up/down in the chat UI)
   calls `store_feedback()` in `sql_hallucination_guard.py`, which appends
   one JSON record per rating to `eval/user_feedback.jsonl`: question,
   route, SQL, final answer, rating, comment, and a 3-turn conversation
   history snapshot for context. This is real-user signal, not synthetic.
2. **RAG's 3-gate verification** (`rag_verifier.py` — product-exists,
   retrieval-quality, answer-grounding) runs on every live RAG query and
   is returned to the frontend as `rag_verification`; the audit log
   (`observability/audit_logger.py`) captures `route` and `latency_ms` per
   query, so gate pass/fail rates and per-route latency are derivable from
   production logs even without a dedicated online-eval dashboard.

There's no automated aggregation of `eval/user_feedback.jsonl` or the
audit log into a dashboard today — both are append-only JSON/JSONL files
meant to be analyzed ad hoc.

## Benchmark results

Latest recorded results, in `assets/`:

**Text2SQL — per-model accuracy** (`text2sql_accuracy.png`), 80% threshold:

| Approach | Accuracy |
|---|---|
| Databricks (baseline NL-to-SQL) | 16.7% |
| Vanilla (plain LLM SQL generation, no guardrails) | 41.7% |
| **Reliable** (this system — self-correction + hallucination guard) | **95.8%** |

**Router — mode-selection accuracy** (`router_accuracy.png`), 80% threshold:

| Route | Accuracy |
|---|---|
| Hybrid (`both`) | 86.7% |
| RAG | 95.8% |
| Text2SQL | 95.2% |

**RAG — answer accuracy** (`rag_accuracy.png`), 80% threshold:

| Approach | Accuracy |
|---|---|
| GPT (plain LLM, no retrieval grounding) | 70.3% |
| **Reliable_RAG** (this system — hybrid retrieval + 3-gate verification) | **95.9%** |

The consistent framing across all three charts — an unguarded/baseline
approach vs. this system's guarded pipeline, against an 80% threshold —
is the headline result: retries, validation, and verification gates are
what take each pipeline from below-threshold to comfortably above it.
`Hybrid` routing is the one metric that stays closest to (but still above)
the threshold, consistent with it being the hardest classification case
(it requires recognizing a question needs *both* pipelines, not just
picking the more obviously-matching one).

## Known gaps

- `rag_eval.csv` names metrics (`Recall@3`, `NDCG@5`, `citation_support`,
  `hallucination_flag`, `grounded_refusal_accuracy`) that aren't yet
  implemented in `eval/metrics/` — the dataset's design is ahead of the
  metric code.
- The evaluation driver script that produced the current `assets/*.png`
  charts isn't in the repo (see [Evaluation pipeline](#evaluation-pipeline)).
- Online signals (`eval/user_feedback.jsonl`, audit log) aren't
  aggregated anywhere — no dashboard, no scheduled rollup.
