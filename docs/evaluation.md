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

Of the six, **Faithfulness is the only one that needs no ground truth** — it
scores `actual_output` against `retrieval_context` alone, with no reference
answer or "ideal chunks" required. The other five (Accuracy, AnswerRelevancy,
ContextualPrecision, ContextualRecall, ContextualRelevancy) all compare
against a reference answer or ideal-chunk list from `eval/dataset/*.csv`, so
they only run through the offline driver below. Because Faithfulness has no
such dependency, its scoring formula is factored out into
`eval/metrics/_faithfulness_core.py` (`faithfulness_score()`) — a
deepeval-free function — so it can also run on every live RAG query without
pulling deepeval's dependency tree into the serving path. `faithfulness.py`'s
`FaithfulnessMetric` (used by the offline driver) and the live path in
`backend/services/agent/tools/rag_tool.py` both call the same function, so
online and offline faithfulness scores are computed identically. See
[Online evaluation](#online-evaluation) below.

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

Production traffic feeds several lightweight, always-on signals — no offline
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
   query.
3. **RAG faithfulness** — every live RAG query is also scored with the same
   `faithfulness_score()` formula the offline `FaithfulnessMetric` uses (see
   above), via `observability/metrics/rag_quality.py`'s `rag_quality_tracker`
   (an in-process rolling window, last 500 scores).
4. **Token cost** — `observability/metrics/costs.py`'s `cost_tracker` records
   input/output tokens and estimated USD cost per LLM call. Currently only
   `sql_generation.py` calls `cost_tracker.record()` — the RAG generation
   call in `backend/services/rag/generation/generation.py` does not yet, so
   cost totals undercount `rag`/`both`-route queries.

### Live dashboard

`GET /metrics/live` (`backend/services/api/agent.py`) aggregates all of the
above into one JSON response on every call — no offline dataset, no stored
aggregation table, just a fresh read of the audit log tail, the feedback
file tail, and the two in-process trackers each time it's hit:

- `queries` — total + recent (last `window_minutes`, default 15) query
  counts, broken down `by_route`, read from `observability/logs/audit.log`
  (`event == "agent.query"` lines).
- `latency_ms` — avg/p50/p95 over the same audit-log window.
- `feedback` — good/bad counts and satisfaction rate from
  `eval/user_feedback.jsonl`.
- `cost` — `cost_tracker.summary()` (session-lifetime, resets on restart).
- `rag.faithfulness` — `rag_quality_tracker.summary()`: count, avg, p50,
  p95, and the last 20 raw scores.

The frontend polls this endpoint every 5s from the **Dashboard** tab of the
Settings panel (`frontend/src/components/debug/MetricsDashboard.tsx`,
opened via the gear icon → `DebugPanel.tsx`), which was previously
diagnostics-only (now a second "Diagnostics" tab).

**Still gaps:** `eval/user_feedback.jsonl` and the audit log are still plain
append-only files — `/metrics/live` re-tails them on every request rather
than reading from a proper aggregation store, so this doesn't scale past
"tail the last couple thousand lines." `cost_tracker` and
`rag_quality_tracker` are in-process and reset on every backend restart —
neither is persisted. And only Faithfulness runs online; Accuracy,
AnswerRelevancy, and the three Contextual* metrics still require the
offline driver (see [Known gaps](#known-gaps)).

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
  `GET /eval/results` and `GET /eval/rows` (`backend/services/api/agent.py`)
  already exist to serve `eval/eval_result/*.jsonl` to the frontend, but
  return "no eval results found" until that driver is rewritten and run —
  they aren't wired into the Dashboard tab for this reason.
- `eval/user_feedback.jsonl` and the audit log are aggregated now (see
  [Online evaluation](#online-evaluation)'s live dashboard), but only by
  re-tailing the raw files on every request — no scheduled rollup, no
  retention/downsampling, nothing persisted across a backend restart for
  `cost_tracker` or `rag_quality_tracker`.
- Only RAG Faithfulness runs online. Accuracy, AnswerRelevancy,
  ContextualPrecision, ContextualRecall, and ContextualRelevancy all need a
  reference answer or "ideal chunks" that live queries don't have, so they
  stay offline-only until the missing driver above is rewritten.
- Text2SQL's 8 metrics (`text2sql_metrics.py`) have no live counterpart at
  all yet — the live dashboard currently only tracks RAG faithfulness,
  Text2SQL/RAG query volume, latency, feedback, and cost.
