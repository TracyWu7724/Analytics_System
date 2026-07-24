# Knowledge Preparation Pipeline — Design

How PDFs become searchable, structured knowledge for the RAG pipeline. Two
build paths feed the same downstream artifacts (a FAISS vector index +
JSONL metadata, plus a knowledge graph), consumed at query time by
`HybridRetriever` and `KGRetriever`.

```
                 ┌─────────────────────┐        ┌──────────────────────────┐
Batch (offline)  │ indexer.py          │        │ data/rag/embedding/      │
28 seed PDFs  →  │ IndexingPipeline.run│  ────► │  embeddings_<model>.npy  │
                 └─────────────────────┘        │  embeddings_<model>     │
                                                 │    _meta.jsonl           │
                                                 │  embeddings_<model>     │
                                                 │    .index                │
                                                 └──────────────────────────┘

                 ┌─────────────────────┐        ┌──────────────────────────┐
Incremental      │ incremental.py      │        │ embeddings_<model>_2     │
(online, per     │ IncrementalIndexer  │  ────► │   .index / _meta_2.jsonl │
upload)       →  │   .add_pdf()        │        │ (merged into existing)   │
                 └──────────┬──────────┘        └──────────────────────────┘
                            │
                            ▼
                 ┌─────────────────────┐        ┌──────────────────────────┐
                 │ kg_builder.py       │  ────► │ index/knowledge_graph.json│
                 │  (async, new chunks │        │ NetworkX DiGraph, JSON    │
                 │   only)             │        └──────────────────────────┘
                 └─────────────────────┘
```

---

## 1. Batch indexing — offline bulk build

Entry point: `backend/services/rag/indexing/indexer.py`, run directly
(`python -m backend.services.rag.indexing.indexer`) or via
`IndexingPipeline.from_config(IndexingConfig(...))`. Used once to build the
initial corpus from a directory of PDFs (the 28 Loctite datasheets in
`data/rag/raw_files/`).

**Steps** (`IndexingPipeline.run()`):

1. **`parser.py` — `PdfParser.parse()`**: partitions each PDF into
   `unstructured` elements (`hi_res` strategy, table structure inferred).
   Derives a stable `product_id` from the filename
   (`LOCTITE-AA-332-en_GL.pdf` → `LOCTITE-AA-332`, stripping the trailing
   locale suffix) and a `product_uuid` — the first 10 hex chars of
   `sha1(product_id)` — used as a stable join key across the vector index,
   metadata, and knowledge graph.
2. **`chunker.py` — `Chunker.chunk()`**: `chunk_by_title` groups elements
   into chunks (merge under 700 chars, cap at 1000), then:
   - strips two known boilerplate footers (Henkel distribution notice,
     "for the most direct access to local sales…")
   - stops processing entirely at the first chunk containing "conversions"
     (unit-conversion tables at the tail of every datasheet — treated as a
     document-level cutoff marker, not just excluded)
3. **`embedded.py` — `Embedder.encode()`**: encodes chunk texts with a
   `SentenceTransformer` model, L2-normalized so inner product ≡ cosine
   similarity. Saved as `embeddings_<model>.npy` + `embeddings_<model>
   _meta.jsonl` (one JSON object per chunk: `id`, `text`, `product_id`,
   `product_uuid`, `source_file`, `chunk_index`).
4. **`indexer.py` — `FaissIndexer.build()`**: wraps the embeddings in a
   `faiss.IndexFlatIP`, saved as `embeddings_<model>.index`, plus a
   `index_manifest.json` summary (chunk count, model, file paths).

## 2. Incremental indexing — online, per-upload

Entry point: `POST /upload/pdf` (`backend/services/api/agent.py`) →
`backend/services/rag/indexing/incremental.py`. Runs on every user PDF
upload without touching the rest of the index.

1. Parse + chunk the single PDF (`fast` strategy, no table structure — a
   deliberate latency trade-off for uploads vs. the batch build).
2. Embed only the new chunks.
3. Load the existing FAISS index if present, else create a fresh
   `IndexFlatIP`; append the new vectors; re-save.
4. Append new metadata lines to the `_meta_2.jsonl` file, de-duplicating by
   chunk `id` (`product_uuid::chunk_index`) against what's already on disk.
5. If any new chunks were actually written, kick off
   `KGBuilder.build_async()` in a daemon thread for *only those chunks* — KG
   construction never blocks or fails the upload response.

**Filename convention note:** the live app resolves its RAG paths via
`_resolve_rag_paths()` in `agent.py`, which always looks for the `_2`
suffix (`embeddings_<model>_2.index` / `_meta_2.jsonl`). `IncrementalIndexer`
writes to those exact paths. The batch pipeline (`indexer.py`) does **not**
— it writes unsuffixed filenames. In practice, the currently-deployed index
was seeded through the incremental path (or renamed by hand); running the
batch pipeline fresh today would produce files the live app won't pick up
without a manual rename. See [Known gaps](#5-known-gaps) below.

## 3. Knowledge graph construction

Triggered only from the incremental upload path
(`IncrementalIndexer.add_pdf` → `KGBuilder.build_async`), never from the
batch pipeline.

- **`entity_extractor.py`**: spaCy NER over chunk text (labels `PRODUCT`,
  `ORG`, `PERSON`, `GPE`, `LOC`, `NORP`, `EVENT`, `WORK_OF_ART`), plus a
  regex for product codes (`LOCTITE 243`, `3M VHB-4950`, …) that NER alone
  tends to miss. Deduplicated case-insensitively per chunk.
- **`relation_extractor.py`**: three regex patterns —
  `is_used_for`, `is_compatible_with`, `replaces` — matched only when the
  regex subject overlaps with an already-extracted entity, to keep noise
  down. Purely pattern-based; no LLM fallback for relations the patterns
  miss (contrast with Text2SQL's `entity_matcher.py`, which *does* have an
  LLM-judge fallback for ambiguous value matches — a different subsystem,
  not to be confused with this one).
- **`knowledge_graph.py`**: a thin wrapper around a NetworkX `DiGraph`.
  `add_entity` increments a `mentions` counter on repeat sightings instead
  of duplicating nodes; `add_relation` auto-creates any missing endpoint
  nodes; `expand_entity` does an undirected `ego_graph` BFS out to N hops
  for multi-hop neighbor lookup; the whole graph persists as NetworkX
  node-link JSON at `INDEX_DIR/knowledge_graph.json`.

## 4. Query-time consumption

- On startup, `agent.py` loads the KG once from disk (silently proceeds
  with an empty graph if the file doesn't exist yet — first upload builds
  it).
- `kg_retriever.py` (`KGRetriever.expand_query`) extracts entities from the
  *user's question* the same way (product-code regex + spaCy NER), looks up
  1-hop KG neighbors for each, and appends up to 5 expansion terms to the
  text sent to retrieval — e.g. "what replaces LOCTITE 243?" pulls in
  "LOCTITE 2400" before the vector/keyword search even runs.
- `hybrid_retriever.py` (`HybridRetriever.retrieve`): expands the query via
  KG if a graph is passed in, runs FAISS vector search and keyword search
  on the expanded text in parallel, merges hits by chunk `id` (keeping the
  higher-scoring copy), and reranks to the final `top_k` with an optional
  cross-encoder.

## 5. Known gaps

- **Batch/incremental filename mismatch** — `indexer.py` output isn't
  directly loadable by the running app (see §2). No code currently
  reconciles this; it's a manual step today.
- **Embedding model drift** — the batch pipeline's `__main__` block
  hardcodes `intfloat/e5-base-v2`; the deployed `.env` uses
  `BAAI/bge-base-en-v1.5`. Re-running the batch pipeline as-is would
  silently build an index with the wrong embedding space for the live app.
- **KG only grows incrementally** — a from-scratch batch rebuild of the
  vector index would produce zero knowledge-graph entries unless someone
  separately runs `KGBuilder.build_from_chunks()` over the full corpus.
- **No delete/replace path** — re-uploading a PDF after a chunking or
  parsing change appends new chunks under new `chunk_index` values; it
  doesn't retire the old ones, so the index can accumulate duplicate/stale
  content for a product over time.
- **KG expansion isn't product-scoped** — vector search supports
  `search_within_product(product_uuid, ...)`, but `KGRetriever.expand_query`
  has no equivalent restriction, so a 1-hop neighbor from an unrelated
  product could enter the expanded query.

## 6. Future plan

1. **Unify the batch and incremental paths** — make `indexer.py` write (or
   be pointed at) the same `_2`-suffixed filenames and read the embedding
   model from `.env`, so a full offline rebuild is a drop-in replacement
   for the live index.
2. **Backfill the KG from the full corpus** — run `KGBuilder` once over
   `data/rag/corpus/corpus_2.0.jsonl` so graph coverage isn't limited to
   whatever's been uploaded incrementally since the KG feature shipped.
3. **LLM fallback for relation extraction** — extend
   `relation_extractor.py` with an LLM pass for relations the three regex
   patterns miss, mirroring the LLM-judge fallback pattern already used in
   Text2SQL's `entity_matcher.py`.
4. **Delete/replace on re-upload** — key incremental updates off
   `product_uuid` so re-uploading a product's PDF retires its previous
   chunks instead of only appending.
5. **Product-scoped KG expansion** — thread `product_uuid` through
   `KGRetriever.expand_query` so multi-hop expansion can be restricted to
   the current product when one is known, matching how vector search
   already scopes itself.
