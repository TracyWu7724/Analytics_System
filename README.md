# Analytics System
Natural language interface to data and product manuals query. Users ask questions in plain English; the system routes to Text2SQL, RAG, or both, and returns results with sources and debug info.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — system overview, components, request workflow, data flow, routing logic, sequence diagrams
- [`docs/knowledge_prep_design.md`](docs/knowledge_prep_design.md) — how PDFs become searchable knowledge (batch + incremental indexing, knowledge graph construction)
- [`docs/evaluation.md`](docs/evaluation.md) — datasets, metrics, evaluation pipeline, benchmark results
- [`docs/deployment.md`](docs/deployment.md) — local dev, Docker deployment, environment variables, security considerations

**Latest benchmark results** (full breakdown in [`docs/evaluation.md`](docs/evaluation.md)):

| Pipeline | Baseline | This system |
|---|---|---|
| Text2SQL accuracy | 16.7% (Databricks) / 41.7% (vanilla LLM) | **95.8%** |
| RAG answer accuracy | 70.3% (plain LLM) | **95.9%** |
| Router mode-selection accuracy | — | 86.7–95.8% across routes |

## Features

- **Hybrid Text2SQL + RAG agent** — an LLM router classifies each question as `sql`, `rag`, `both`, or `schema`, with a keyword-based fallback if the LLM call fails (see `docs/architecture.md#routing-logic`)
- **Self-correcting SQL generation** — up to 3 retries per query, with a hallucination guard that validates generated SQL against the real schema, column semantics, and known database values before execution
- **Verified RAG** — hybrid FAISS + keyword retrieval, knowledge-graph query expansion, and a 3-gate check (product exists → retrieval quality → answer grounding) before an answer is returned
- **Hybrid synthesis** — for questions needing both data and knowledge, a synthesizer node combines SQL results and document context into one narrative rather than concatenating them
- **MDL semantic layer** — business metric/join definitions (`backend/mdl/schema.yaml`) injected automatically into SQL generation, so "revenue" always means `SUM(net_sales)`
- **Auto-generated hybrid index** — database values are profiled and indexed automatically (no manual entity lists) to validate SQL filter values at query time
- **Knowledge graph over product documents** — PDF uploads are parsed, chunked, embedded, and mined for entities/relations, used to expand retrieval queries (e.g. "what replaces LOCTITE 243?")
- **Role-based access control** — per-role table and document denylists, enforced inside the agent graph rather than filtered after the fact
- **Streaming progress** — SSE-based step-by-step progress (`routing → generating → executing → validating`) rendered live in the chat UI
- **User feedback capture** — thumbs up/down on any answer, stored with a conversation-history snapshot for later analysis
- **In-house observability** — per-query latency and routing/SQL metadata logged to `observability/logs/audit.log`, no external tracing service required

## Configuration
### 1. LLM API

At least one provider key is required in `.env`:

```
OPENAI_API_KEY=sk-...     # enables gpt-4o, gpt-4o-mini
GEMINI_API_KEY=AIza...    # enables gemini-2.5-flash
```

Available models are defined in `backend/services/text2sql/generation/llm_registry.py` (`LLM_MODELS`); the default is `gpt-4o`. `GET /llm-models` returns which models are actually usable given the keys present in the environment.

### 2. Databricks token
**Databricks credentials** (`DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_TOKEN`):

The backend connects to Databricks with a personal access token (PAT) — `databricks_service.py` only reads `DATABRICKS_TOKEN`, not the client ID/secret pair. PATs expire, so when queries start failing with `Invalid access token`, generate a new one:

1. Log into the Databricks workspace at the URL in `DATABRICKS_SERVER_HOSTNAME`.
2. Click your profile icon (top right) → **Settings**.
3. Go to the **Developer** tab → **Access tokens** → **Manage** → **Generate new token**.
4. Give it a comment and lifetime (or no expiry), click **Generate**, and copy the token immediately — it's only shown once.
5. Paste it into `.env` as `DATABRICKS_TOKEN=<token>`.

`DATABRICKS_HTTP_PATH` comes from the SQL warehouse, not the token page:

1. In the workspace sidebar, go to **SQL Warehouses**.
2. Open the warehouse you're connecting to → **Connection details** tab.
3. Copy the **HTTP path** value into `.env` as `DATABRICKS_HTTP_PATH`.

After updating `.env`, restart the backend so it picks up the new token.



## Quick Start

```bash
# Frontend
cd frontend
npm run dev

# Backend
cd backend
uvicorn services.api.agent:app --reload
```

## Example

Ask a question in the chat UI (or `POST /agent/query`) and the router picks the pipeline automatically:

| Question | Route | What happens |
|---|---|---|
| "Show total sales for LOCTITE 243" | `sql` | Generates and executes SQL against Databricks, returns the rows as a table |
| "What is the cure time for LOCTITE 243?" | `rag` | Retrieves the product datasheet chunk, verifies it's grounded, answers from documentation |
| "Why did sales of LOCTITE 401 drop this quarter?" | `both` | Runs SQL for the sales numbers *and* RAG for product context, then synthesizes one answer that explains the numbers using the documentation |
| "What tables do you have?" | `schema` | Answered directly from the connected Databricks schema — no LLM call |

```bash
curl -X POST http://localhost:8000/agent/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the cure time for LOCTITE 243?", "llm_model": "gpt-4o"}'
```

```json
{
  "question": "What is the cure time for LOCTITE 243?",
  "route": "rag",
  "route_reasoning": "The question asks for product specifications from documentation.",
  "final_answer": "LOCTITE 243 has a fixture time of 10-20 minutes and a full cure time of 24 hours at room temperature...",
  "sql_query": null,
  "rag_chunks": [{"text": "...", "score": 0.87, "source": "LOCTITE-243-en_GL.pdf"}],
  "error": null
}
```

**Environment variables:**
```
INDEX_DIR          path for index files (schema, value, history, KG)
RAG_EMBED_DIR      path for FAISS index and metadata
RAG_EMBED_MODEL    embedding model (default: sentence-transformers/all-MiniLM-L6-v2)
RAG_RERANKER_MODEL optional cross-encoder for reranking
AUDIT_LOG_DIR       directory for the audit log (default: observability/logs/)
```

**Tracing:** each `/agent/query` call is timed and logged in-house — no external service required. `observability/audit_logger.py` writes one JSON line per query to `observability/logs/audit.log` with `question`, `route`, `sql_query`, `sql_table`, `session_id`, `user_id`, `llm_model`, and `latency_ms`.

### Deployment (Docker)

```bash
docker compose -f docker/docker-compose.yml up --build
```

Backend → http://localhost:8000, frontend (nginx) → http://localhost:80. Full details (volumes, S3 cold-start sync, env vars, security considerations): [`docs/deployment.md`](docs/deployment.md).

## Domain definitions

These are encoded in `backend/mdl/schema.yaml` and injected automatically:

- **Revenue** = `SUM(net_sales)`
- **Usage** = `SUM(units_sold)`
- **Profit** = `SUM(net_sales) - SUM(cogs)`
- **Margin** = `(SUM(net_sales) - SUM(cogs)) / NULLIF(SUM(net_sales), 0) * 100`
- `product` joins `sales` on `product_id`

## Roadmap

Detailed design and rationale: [`docs/knowledge_prep_design.md`](docs/knowledge_prep_design.md).

- **Unify batch and incremental indexing** — the offline bulk pipeline (`indexer.py`) and the online per-upload pipeline (`incremental.py`) currently write different filename conventions and default to different embedding models; reconcile them so a full offline rebuild is a drop-in replacement for the live index.
- **Backfill the knowledge graph from the full corpus** — the KG currently only grows from incremental PDF uploads; run it once over the full batch corpus so graph coverage isn't gated on upload history.
- **LLM fallback for relation extraction** — extend the regex-only relation extractor with an LLM pass for relations the patterns miss, mirroring the LLM-judge fallback already used in Text2SQL's entity matching.
- **Delete/replace on re-upload** — re-uploading a product's PDF today only appends chunks; key updates off `product_uuid` so old chunks get retired.
- **Product-scoped KG expansion** — restrict knowledge-graph query expansion to the current product when one is known, matching how vector search already scopes itself.
