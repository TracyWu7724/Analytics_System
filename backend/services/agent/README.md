# backend/services/agent — module map

This is a directory-level reference for `backend/services/agent/`: the
LangGraph orchestration layer. For the one-level-up picture (how `agent/`
relates to `rag/`, `text2sql/`, `api/`) see
[`../README.md`](../README.md). This document goes one level deeper, into
the agent's state, graph topology, and nodes.

## Layout

```
agent/
├── state.py       AgentState — the single TypedDict every node reads/writes
├── graph.py        build_agent() — StateGraph topology
├── progress.py      Per-trace_id SSE + span-tracing event registry
├── nodes/            Thin LangGraph nodes (control flow only)
└── tools/            The actual pipeline logic nodes delegate to
```

**Pattern**: `nodes/*.py` are deliberately thin — they read `AgentState`,
call into `tools/*.py` for the real work, emit progress, and write the
result back into state. If you're changing *behavior* (how SQL gets
generated, how retrieval works), you almost always want `tools/`, not
`nodes/`.

## `state.py` — the contract every node shares

`AgentState` is a `TypedDict` passed through the whole graph. Every field
is `Optional` because not every node runs on every request (e.g.
`sql_*` fields stay `None` on a rag-only route). It's organized into
sections:

| Section | Fields |
|---|---|
| Input | `question`, `history`, `uploaded_table`, `llm_model` |
| Identity | `session_id`, `user_id`, `trace_id` |
| Auth / data-access | `denied_tables`, `denied_rag_sources` |
| Routing | `route`, `route_reasoning` |
| SQL pipeline | `sql_table`, `sql_tables`, `sql_query`, `sql_rows`, `sql_error`, `sql_attempts` |
| RAG pipeline | `rag_answer`, `rag_chunks`, `rag_error`, `rag_verification` |
| MDL / semantic layer | `mdl_context`, `mdl_metrics_referenced` |
| Provenance | `entity_resolutions` |
| Output | `final_answer`, `error` |

LangGraph nodes are just functions `(state) -> dict`. The dict a node
returns gets merged back into this state — nodes never mutate `state`
directly.

## `graph.py` — topology

`build_agent(...)` wires 7 nodes into a `StateGraph(AgentState)`:

```
router → sql_node | rag_node | both | schema_node
sql_node    → retry_sql | rag_node | synthesizer | end_sql
rag_node    → sql_node | synthesizer | end_rag
synthesizer → END
```

- `sql_node` has an internal self-correction loop (up to 3 attempts,
  driven by `should_retry_sql`).
- `"both"` runs `sql_node` first, then `rag_node`, then `synthesizer`.
- For `"sql"` or `"rag"`-only routes, `end_sql` / `end_rag` set
  `final_answer` inline before reaching `END`.

Runtime dependencies (`data_service`, FAISS paths, indexes, `kg`) are
bound into node functions via `functools.partial` at build time, so the
compiled graph itself stays a pure function of `AgentState` — nodes don't
need to know where their dependencies came from.

## `progress.py` — SSE + tracing plumbing

A `trace_id → Queue` registry. Every node calls
`emit(trace_id, step, label)` at each meaningful step (e.g. "Generating
SQL..."). This does two things at once:

1. Pushes an event onto the SSE queue that drives the frontend's live
   progress checklist.
2. Persists the same event as a span via `observability/trace_log.py`,
   which backs the `/traces` waterfall view.

If the trace isn't registered (a non-streaming call), the SSE push is a
silent no-op — the span is still recorded.

## `nodes/` — thin wrappers, one per pipeline step

| File | Role |
|---|---|
| `router.py` | Classifies the question into `sql`\|`rag`\|`both`\|`schema`. Regex fast-path for "what tables do you have" (skips the LLM entirely) → LLM call with a JSON-output prompt → keyword-overlap fallback if the LLM call throws. All routing logic lives in this file — nothing delegated to `tools/`. |
| `schema_node.py` | Terminal node for schema questions; answers directly from `data_service.get_table_names()`, no LLM call. |
| `sql_node.py` | Owns the retry loop (`MAX_ATTEMPTS = 3`): pick table(s) → resolve product mentions → pre-check values exist → generate SQL → validate (schema hallucination check, column-semantics check, value check) → execute → diagnose empty results. Delegates generation/validation to `tools/sql_tool.py` and `text2sql/generation/sql_hallucination_guard.py`; this file is the control flow around those calls. `should_retry_sql` is its conditional-edge function (retry vs. handoff to rag vs. synthesizer vs. end). |
| `rag_node.py` | Calls `tools/rag_tool.py`'s `run_rag(...)` and writes `rag_answer`/`rag_chunks`/`rag_error`/`rag_verification` back to state. On a `both` route it rewrites the question sent to the RAG *generation* prompt to explicitly exclude sales/revenue framing, so the doc-retrieval LLM doesn't say "the docs don't cover revenue" and get flagged as non-substantive by the synthesizer's refusal filter. `retrieval_question=question` (the original, unmodified question) is passed separately so FAISS retrieval itself isn't affected by that framing tweak. `should_continue_after_rag` is its conditional-edge function. |
| `synthesizer.py` | Only runs on `both`. Merges SQL rows + RAG answer into one narrative via an LLM call, with three degraded-mode fallbacks handled before ever calling the LLM: SQL-only (no RAG context), RAG-only (no DB rows), neither (clean refusal). `_rag_is_substantive()` decides whether the RAG side contributed anything worth citing — it checks for refusal phrases but treats long mixed answers as substantive even if a refusal phrase is present, since real content can coexist with a partial refusal. |

## `tools/`

`sql_tool.py` and `rag_tool.py` hold the actual pipeline logic (table
picking, SQL generation/execution; hybrid retrieval + generation
respectively). Nodes call into these rather than implementing logic
inline — this is the "nodes are thin, tools do the work" pattern also
noted in [`../README.md`](../README.md).
