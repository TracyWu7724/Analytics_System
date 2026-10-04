# backend/services — module map

This is a directory-level reference for `backend/services/`: what each
module does and how they call into each other. For the system-level
picture (frontend, auth, observability, full request flow, routing
decision logic) see [`docs/architecture.md`](../../docs/architecture.md) —
this document doesn't repeat that, it goes one level deeper into the
Python code itself.

## Layout

```
services/
├── api/          3 FastAPI apps — only agent.py is actually deployed
├── agent/        LangGraph orchestration: state, graph topology, nodes, tools
├── rag/          Document pipeline: PDF ingestion, knowledge graph, retrieval, generation
├── text2sql/     Structured-data pipeline: DB access, value indexes, SQL generation, guardrails
└── utils/        Small shared helpers (spaCy singleton)
```

**"Graph" means two unrelated things here — don't conflate them:**

| | LangGraph | Knowledge Graph |
|---|---|---|
| What | Orchestration framework — `StateGraph` wiring router → pipeline nodes → synthesizer | RAG data structure — a `networkx.DiGraph` of product entities/relations |
| File | `agent/graph.py` (`build_agent()`) | `rag/kg/knowledge_graph.py` (`KnowledgeGraph` class) |
| Nodes are | Python functions (`router_node`, `sql_node`, `rag_node`, ...) | Entities (`"loctite 243"`, ...) |
| Edges are | Control flow between pipeline steps | Relations (`is_used_for`, `replaces`, `co_occurs_with`) |
| Decides | *Which pipeline* runs for a question | What to *add to a query* before retrieval (KG-RAG expansion) |

They intersect at exactly one point: `rag_node` (a LangGraph node) calls
`tools/rag_tool.py` → `hybrid_retriever.retrieve(..., kg=kg)` →
`KGRetriever.build_expanded_query()`, which reads the knowledge graph
during one step of a LangGraph run. The KG has no influence on LangGraph's
control flow — it's just data one node happens to consult.

## `api/` — three FastAPI apps, one of them live

| File | Status | What it is |
|---|---|---|
| `agent.py` | **Live** — this is what `uvicorn backend.services.api.agent:app` actually serves (see `docs/deployment.md`) | Combined Text2SQL + RAG agent. Builds the LangGraph agent once at startup, exposes `/agent/query`, `/agent/query/stream` (SSE), `/upload`, `/upload/pdf`, `/traces*`, `/latency/stats`, `/quality/stats`, `/metrics/live`, `/kg/stats`, `/mdl/*`, auth endpoints. |
| `text2sql.py` | Legacy, not imported by `agent.py`, has its own `app = FastAPI(...)` and its own LangSmith `@traceable` wrapping | An earlier, SQL-only version of the API. Left in the repo but not part of the current deployment. |
| `rag.py` | Legacy, same situation — its own `app = FastAPI(title="Henkel RAG API", ...)` | An earlier, RAG-only API with its own user registration/conversation endpoints. Not part of the current deployment either. |

If you're tracing a live request, start in `agent.py` — the other two are
historical and safe to ignore unless you're specifically archaeology-ing
how the API evolved.

## `agent/` — LangGraph orchestration

| File | Role |
|---|---|
| `state.py` | `AgentState` — the single `TypedDict` every node reads/writes. Sectioned into Input, Identity, Auth, Routing, SQL pipeline, RAG pipeline, MDL, Provenance, Output. Every field is `Optional` so a node can be skipped cleanly. |
| `graph.py` | `build_agent(...)` — constructs the `StateGraph(AgentState)`, wires nodes, compiles it. This is the file to read for topology (see the ASCII diagram in its own docstring). |
| `progress.py` | Per-`trace_id` event queue. Nodes call `emit(trace_id, step, label)`; the SSE endpoint in `api/agent.py` drains it to the frontend as live progress events, and the same events are persisted as spans for the `/traces` waterfall view. |
| `nodes/router.py` | Classifies the question: regex schema-fast-path → LLM classification (`sql`\|`rag`\|`both`) → keyword-overlap fallback if the LLM call fails. |
| `nodes/schema_node.py` | Answers "what tables do you have" directly from `data_service`, no LLM call. |
| `nodes/sql_node.py` | Thin LangGraph wrapper around `tools/sql_tool.py`; owns the retry-loop decision (`should_retry_sql`, up to 3 attempts) and the `both`-route handoff to `rag_node`. |
| `nodes/rag_node.py` | Thin LangGraph wrapper around `tools/rag_tool.py`; owns the `both`-route handoff logic (`should_continue_after_rag`). |
| `nodes/synthesizer.py` | Only runs on the `both` route — one LLM call that merges `sql_rows` + `rag_answer` into a single narrative answer. |
| `tools/sql_tool.py` | The actual Text2SQL work: table selection, SQL generation, execution, hallucination-guard validation. Called by `sql_node`, and also imported directly by `api/agent.py` for the standalone SQL path. |
| `tools/rag_tool.py` | The actual RAG work: query prep → KG-expanded hybrid retrieval → 3-gate verification → generation (`run_rag(...)`). Called by `rag_node`, and also imported directly by `api/agent.py`'s `/rag/query` endpoint. |

**Pattern**: `nodes/*.py` are deliberately thin — they read `AgentState`,
call into `tools/*.py` for the real work, emit progress, and write the
result back into state. If you're changing *behavior* (how SQL gets
generated, how retrieval works), you almost always want `tools/`, not
`nodes/`.

## `rag/` — document pipeline

| Subpackage / file | Role |
|---|---|
| `rag_config.py` | `IndexingConfig`, `QueryPreparationConfig` — dataclasses with the tunable knobs (chunk size, embed model, etc). |
| `rag_modeling.py` | Shared dataclasses: `CorpusChunk`, `RetrievalResult`, `PreparedQuery`. |
| `rag_verifier.py` | The 3 verification gates: `verify_product_exists` (pre-retrieval, hard), `verify_retrieval_quality` (post-retrieval, hard), `verify_answer_grounding` (post-generation, soft). |
| `indexing/parser.py` | PDF → `unstructured` elements (hi-res), plus product ID/UUID extraction from filename. |
| `indexing/chunker.py` | Elements → cleaned text chunks (`chunk_by_title`, boilerplate stripping). |
| `indexing/embedded.py` | `Embedder` — SentenceTransformer wrapper, encode + persist. |
| `indexing/indexer.py` | `FaissIndexer` — builds/persists the FAISS index; orchestrates the full parse→chunk→embed→index pipeline. |
| `indexing/incremental.py` | `IncrementalIndexer` — appends one new PDF's chunks into an existing index without a full rebuild (used by `/upload/pdf`). |
| `kg/entity_extractor.py` | spaCy NER + product-code regex → `Entity` list. |
| `kg/relation_extractor.py` | 3 regex patterns (`is_used_for`, `is_compatible_with`, `replaces`) → `Relation` triples. |
| `kg/knowledge_graph.py` | `KnowledgeGraph` — thin `networkx.DiGraph` wrapper: `add_entity`/`add_relation`, `expand_entity` (ego-graph BFS), `neighbors_with_predicates`, JSON save/load. |
| `kg/kg_builder.py` | `KGBuilder.build_from_chunks(...)` — runs extraction over chunks, populates the graph, adds co-occurrence edges as a fallback signal, persists to disk. Triggered async after PDF upload. |
| `pre_retrieval/query_rewrite.py` | `QueryRewriter` — lowercase/normalize + rapidfuzz spell-correction against known product vocab. |
| `pre_retrieval/query_expansion.py` | `QueryExpander` — synonym expansion + comparative-pattern detection ("weaker than X" → adds concept queries), produces a `PreparedQuery`. |
| `retrieval/vector_store.py` | `FaissVectorStore` — dense search, global and per-product. |
| `retrieval/keyword_retriever.py` | Dependency-free BM25-style lexical search. |
| `retrieval/kg_retriever.py` | `KGRetriever.build_expanded_query(...)` — extracts entities from the query, expands via the KG, appends neighbor names to the retrieval query. |
| `retrieval/reranker.py` | `Reranker` — cross-encoder if `RAG_RERANKER_MODEL` is configured, else a lexical (`SequenceMatcher`) fallback. |
| `retrieval/hybrid_retriever.py` | `HybridRetriever.retrieve(...)` — the actual call site that ties vector + keyword + KG expansion + rerank together. This is the one class most retrieval-path changes touch. |
| `retrieval/retriever.py` | An alternate/simpler retrieval service; check current call sites before assuming this is on the live path (it isn't wired into `tools/rag_tool.py`). |
| `generation/generation.py` | Final answer generation. Calls the `google-genai`/`openai` SDKs **directly**, bypassing LangChain — see the caveat below. |

**Caveat worth knowing**: `generation/generation.py`'s actual
answer-writing LLM call does not go through LangChain's chat model
wrappers. This means it's invisible to LangSmith/Phoenix-style
auto-instrumentation (anything that hooks LangChain's callback system) —
`observability/metrics/costs.py`'s `record_llm_usage()` exists specifically
to paper over this by handling 3 different SDK response shapes by hand.

## `text2sql/` — structured-data pipeline

| Subpackage / file | Role |
|---|---|
| `models.py` | Pydantic request models (`QueryRequest`, etc). |
| `cache_service.py` | Small in-memory TTL cache used by a few DB-facing helpers. |
| `value_index.py` | Older/simpler IR-based distinct-value index (hash + BM25 prefilter + fuzzy) — largely superseded by `indexing/hybrid_value_index.py`, kept for the fallback path. |
| `query_value_extractor.py` | Pulls candidate filter values out of the raw question (regex + spaCy NER) before SQL generation. |
| `db/databricks_service.py` | The Databricks SQL connector — PAT auth, query execution, schema introspection, local SQLite fallback (`init_local_db()`). Central dependency almost everything else in this subpackage takes as a constructor arg. |
| `db/upload_service.py` | CSV upload handling — column-name cleaning, table creation. |
| `indexing/column_profiler.py` | Decides whether a column is worth indexing for value lookup (skips high-cardinality/numeric columns). |
| `indexing/value_canonicalizer.py` | `canonicalize(value)` — normalizes separators/whitespace/abbreviations so "LOCTITE-243" and "LOCTITE 243" compare equal. Used well beyond just SQL values (e.g. reused in the KG-construction ablation experiments). |
| `indexing/inverted_index.py` | The 3 persisted JSON indexes: schema (token→table/col), value (distinct DB values), and historical question→table mappings. |
| `indexing/hybrid_value_index.py` | Facade over `inverted_index.py` adding the profiling gate, canonicalization, and an LLM-judge fallback (`entity_matcher.py`) for ambiguous matches. This is the one `api/agent.py` actually initializes (`init_hybrid_index`). |
| `indexing/entity_matcher.py` | `match_entity(...)` — exact → fuzzy → LLM-judge resolution of a candidate value against the index. |
| `indexing/product_index.py` | Number-centric product name index — indexes "243", "loctite 243", "243 threadlocker", "loctite 243 threadlocker" all pointing at the same canonical product. |
| `indexing/column_embedding_index.py` | Semantic (embedding-based) index over column names, for table-scoring when keyword matching alone doesn't find the right table. |
| `indexing/history_question_indexing.py` | Persists question/SQL pairs to a local SQLite history table (dedup + prune), for surfacing similar past questions. |
| `retrieval/table_matching.py` | Keyword extraction + fuzzy scoring to rank candidate Databricks tables for a question. |
| `retrieval/history_question_retrieval.py` | Fuzzy-matches the current question against recent question history. |
| `generation/llm_registry.py` | `get_llm(model_name)` — the one place model→provider (`ChatOpenAI`/`ChatGoogleGenerativeAI`/Ollama) mapping and client caching happens. |
| `generation/sql_generation.py` | The actual SQL-writing LLM call, MDL context injection, large-dataset-size detection. |
| `generation/sql_correction.py` | `clean_sql_query(...)` plus the mutating-statement guard (blocks `INSERT`/`UPDATE`/`DROP`/etc. — read-only enforcement). |
| `generation/sql_hallucination_guard.py` | The self-correction layer: `validate_schema` (columns/tables exist), `validate_column_semantics`, `validate_logic` (LLM judge — the one guard that costs real $ and, per the observability-comparison writeup, is worth scrutinizing), `diagnose_empty_result`, `validate_query_values`/`validate_sql_values`. Drives `sql_node`'s retry loop. |
| `mdl/mdl_loader.py` | Loads/caches `backend/mdl/schema.yaml` (mtime-based, no restart needed to pick up edits). |
| `mdl/mdl_enricher.py` | Detects which MDL metrics/joins a question references, builds the context block injected into SQL generation. |

## `utils/`

| File | Role |
|---|---|
| `nlp_utils.py` | `load_spacy()` — lazy-loaded, process-wide spaCy model singleton, shared by entity extraction across both `rag/kg/` and `text2sql/query_value_extractor.py`. Loading fails soft (returns `None`) if the model isn't installed — several downstream features degrade quietly rather than crash when this happens (see the KG-RAG findings in `eval/experiments/results/`). |

## Cross-cutting conventions

- **Dual-path imports everywhere**: almost every file has a `try: from ..x import y / except ImportError: from x import y` pair, because these modules get imported both as part of the `backend.services.*` package (normal FastAPI run) and with `backend/` itself on `sys.path` (tests, standalone scripts, the `eval/experiments/` harness).
- **Cost tracking**: any code path that calls an LLM should call `record_llm_usage(model, response, pipeline=...)` from `observability/metrics/costs.py` right after the call — it's a best-effort, never-raises function, already handles LangChain/`google-genai`/`openai` response shapes.
- **Progress events**: any long-running node should call `agent/progress.py`'s `emit(trace_id, step, label)` — this is what drives both the live SSE progress checklist and the `/traces` waterfall view; it's not optional instrumentation, the frontend depends on it.
- **`Optional` state fields**: `AgentState` fields are `Optional` by design so any node can be skipped — don't assume a field is populated without checking `route` first.
