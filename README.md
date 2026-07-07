# Analytics System

Natural language interface to databases and product manuals. Users ask questions in plain English; the system routes to Text2SQL, RAG, or both, and returns results with sources and debug info.

---

## Milestones

### Milestone 1 — Frontend Refactor

**Goal:** make the frontend maintainable through a strict layered architecture.

Each layer has one responsibility and never crosses into another layer's domain:

| Layer | Responsibility | Never contains |
|---|---|---|
| `pages/` | Route-level orchestration | reusable UI, API calls |
| `components/` | Presentational UI | fetch calls, business logic |
| `hooks/` | State + side effects | JSX, direct fetch calls |
| `services/` | All API calls via `apiClient.ts` | React imports, state |
| `types/` | Shared TypeScript contracts | runtime logic |
| `utils/` | Pure, stateless helpers | side effects, API calls |

**How it works:**

```
pages/ChatPage.tsx              ← route entry point
  └→ components/AgentChat.tsx   ← rendering template
       ├→ hooks/useChat.ts       ← all chat state + SSE streaming
       │    └→ services/chatService.ts
       │         └→ services/apiClient.ts   ← single HTTP gateway (auth, timeout, errors)
       ├→ hooks/useLlmModels.ts
       │    └→ services/llmService.ts
       └→ components/chat/RouteBadge.tsx
```

**Key rules enforced:**
- All HTTP goes through `services/apiClient.ts` — no raw `fetch` elsewhere
- Components never call APIs directly — always through a hook
- Shared types live in `types/` — no inline interface definitions

**Directory structure (`frontend/src/`):**

```
├── pages/               # ChatPage, HomePage, DatabasePage, HistoryPage
├── components/
│   ├── chat/            # RouteBadge
│   ├── common/          # LoadingState, ErrorState, EmptyState
│   ├── debug/           # DebugPanel
│   ├── home/            # HeroSection
│   ├── layouts/         # AppLayout, HeaderBar
│   ├── selectors/       # ModelSelector
│   └── table/           # TablePreview
├── hooks/               # useAuth, useChat, useLlmModels, useTables, useQueryHistory
├── services/            # apiClient, chatService, llmService, databaseService,
│                        # feedbackService, uploadService, diagnosticsService
├── types/               # chat.ts, database.ts, api.ts
├── utils/               # parseStream, downloadCsv, formatSql, formatLatency
└── config/              # api.ts
```

---

### Milestone 2 — Auto-Generated Hybrid Index

**Goal:** remove manual entity maintenance — the system automatically profiles and indexes all database values so the hallucination guard can validate SQL filter values at query time.

**How it works:**

```
Databricks tables
  ↓
column_profiler.py      — skip numeric types and high-cardinality (>5000 distinct)
                          columns to keep index size manageable
  ↓
value_canonicalizer.py  — normalize raw values to canonical forms
                          e.g. "LOCTITE-243" → "loctite 243",
                               "N/A" → "not available"
  ↓
inverted_index.py       — build two persistent indexes:
                          • exact hash map (O(1) lookup)
                          • token posting lists (fuzzy match)
                          • sentence-transformer embeddings for reranking
  ↓
hybrid_value_index.py   — thin facade that adds canonicalization at query time
                          and exposes the same search_value() API
  ↓
entity_matcher.py       — query-time resolution:
                          1. exact hash lookup
                          2. token overlap scoring
                          3. embedding cosine reranking
                          4. LLM judge for ambiguous cases (score in suggest range)
```

**Files:**
- `backend/services/text2sql/indexing/column_profiler.py` — decides whether to index a column
- `backend/services/text2sql/indexing/value_canonicalizer.py` — normalizes values + abbreviation expansion
- `backend/services/text2sql/indexing/hybrid_value_index.py` — facade with canonical search
- `backend/services/text2sql/indexing/entity_matcher.py` — full resolution pipeline with LLM judge

---

### Milestone 3 — MDL / Semantic Layer

**Goal:** make Text2SQL business-aware by injecting metric definitions, join relationships, and synonym mappings directly into the SQL generation prompt.

**How it works:**

```
User: "what was the revenue last quarter?"
  ↓
sql_node calls enrich_question()
  ↓
mdl_enricher.py scans the question for metric synonyms
  "revenue" → matches Metric(Revenue, SUM(net_sales))
  ↓
builds a context block:
  "## Semantic Layer (MDL)
   ### Metric Definitions
   - Revenue: SUM(net_sales) — Total net sales amount"
  ↓
context block is injected into the LLM SQL generation prompt
  ↓
LLM generates: SELECT SUM(net_sales) AS Revenue FROM sales WHERE ...
               (not SELECT revenue FROM sales — that column doesn't exist)
```

**The semantic layer is defined in a single YAML file** (`backend/mdl/schema.yaml`):

```yaml
metrics:
  - name: Revenue
    expression: "SUM(net_sales)"
    synonyms: ["revenue", "sales", "total sales", "net revenue", "income"]

  - name: Usage
    expression: "SUM(units_sold)"
    synonyms: ["usage", "units", "volume", "quantity sold"]

  - name: Margin
    expression: "(SUM(net_sales) - SUM(cogs)) / NULLIF(SUM(net_sales), 0) * 100"
    synonyms: ["margin", "gross margin", "profit margin"]

joins:
  - left_table: product
    right_table: sales
    on: "product.product_id = sales.product_id"
```

Edit this file and the **next query picks it up automatically** — the loader uses mtime-based caching so no server restart is needed.

**API endpoints:**
- `GET /mdl/config` — return current metric/join definitions
- `POST /mdl/reload` — force reload from disk

**Files:**
- `backend/mdl/schema.yaml` — the semantic layer definition
- `backend/services/text2sql/mdl/mdl_loader.py` — YAML parser with mtime cache
- `backend/services/text2sql/mdl/mdl_enricher.py` — detects metric/join matches and builds the context block

---

### Milestone 4 — Document Intelligence + KG-RAG

**Goal:** upgrade RAG from chunk retrieval to structured knowledge — extract entities and relations from indexed PDFs into a knowledge graph, then use it to expand queries at retrieval time.

**How it works:**

```
PDF upload (POST /upload/pdf)
  ↓
incremental.py          — parse → chunk → embed → merge FAISS index
  ↓
kg_builder.py           — async background task on new chunks:
                          • entity_extractor.py: spaCy NER + product code patterns
                            e.g. "LOCTITE 243", "3M VHB 4950"
                          • relation_extractor.py: pattern-based triples
                            e.g. (LOCTITE 243, is_used_for, thread locking)
                          • knowledge_graph.py: NetworkX DiGraph, persisted as JSON
  ↓
Query time (POST /agent/query/stream)
  ↓
kg_retriever.py         — expand the query using KG neighbors
                          e.g. "what replaces LOCTITE 243?"
                               → KG finds: LOCTITE 243 → replaces → LOCTITE 2400
                               → expanded query includes "LOCTITE 2400"
  ↓
hybrid_retriever.py     — FAISS + keyword search on the expanded query
                          → retrieves chunks for both products
  ↓
LLM generation          — answers with fuller context
```

**Graceful degradation:** all KG code is wrapped in try/except. If `networkx` or `spacy` are unavailable, retrieval falls back to the original query without expansion.

**API endpoint:**
- `GET /kg/stats` — return node/edge counts from the knowledge graph

**Files:**
- `backend/services/rag/kg/entity_extractor.py` — spaCy NER + product code regex
- `backend/services/rag/kg/relation_extractor.py` — pattern-based triple extraction
- `backend/services/rag/kg/knowledge_graph.py` — NetworkX DiGraph with save/load
- `backend/services/rag/kg/kg_builder.py` — builds graph from chunks, async-safe
- `backend/services/rag/retrieval/kg_retriever.py` — query expansion from KG neighbors
- `backend/services/utils/nlp_utils.py` — shared lazy-loaded spaCy singleton

---

## Running the system

```bash
# Frontend
cd frontend
npm run dev

# Backend
cd backend
uvicorn services.api.agent:app --reload
```

**Environment variables:**
```
INDEX_DIR          path for index files (schema, value, history, KG)
RAG_EMBED_DIR      path for FAISS index and metadata
RAG_EMBED_MODEL    embedding model (default: sentence-transformers/all-MiniLM-L6-v2)
RAG_RERANKER_MODEL optional cross-encoder for reranking
LANGCHAIN_API_KEY  enables LangSmith tracing (optional)
```

## Domain definitions

These are encoded in `backend/mdl/schema.yaml` and injected automatically:

- **Revenue** = `SUM(net_sales)`
- **Usage** = `SUM(units_sold)`
- **Profit** = `SUM(net_sales) - SUM(cogs)`
- **Margin** = `(SUM(net_sales) - SUM(cogs)) / NULLIF(SUM(net_sales), 0) * 100`
- `product` joins `sales` on `product_id`
