# Deployment

How to run the system locally for development, and how it's packaged for
a single-host Docker deployment. There is no CI/CD pipeline or
multi-host/orchestrated deployment (Kubernetes, ECS, etc.) in this repo —
what's documented here is what actually exists.

## Local development

```bash
./setup.sh
```

which runs, equivalent to doing it by hand:

```bash
# Backend — FastAPI with auto-reload
uvicorn backend.services.api.agent:app --port 8000 --reload

# Frontend — React dev server
cd frontend && npm start
```

Backend → http://localhost:8000, frontend → http://localhost:3000. Both
read the repo-root `.env` (via `python-dotenv` / build-time env vars). No
containers involved — this is the fastest loop for iterating on either
side.

## Docker deployment

All deployment files live under `docker/`:

```
docker/
├── docker-compose.yml    # orchestrates backend + frontend
├── Dockerfile.backend    # python:3.11-slim + poppler/tesseract (PDF parsing) + spaCy model
├── Dockerfile.frontend   # multi-stage: node:20-alpine build → nginx:1.27-alpine serve
├── entrypoint.sh         # optional S3 sync, then launches uvicorn
└── nginx.conf            # SPA fallback (try_files → index.html) + gzip
```

```bash
docker compose -f docker/docker-compose.yml up --build
```

- `context: ..` in both build blocks — the build context is the repo
  root even though the compose file lives in `docker/`, so `env_file:
  ../.env` and `COPY backend/ ./backend/`-style paths inside the
  Dockerfiles resolve correctly regardless of which directory you run the
  command from.
- Backend → http://localhost:8000 (health-checked via `GET
  /agent/health`, `curl`-based, 30s interval / 60s start period).
  Frontend (nginx) → http://localhost:80, and only starts once the
  backend healthcheck passes (`depends_on: condition: service_healthy`).
- The frontend's `REACT_APP_API_URL` is a **build-time** arg — baked into
  the static JS bundle by `npm run build` inside the Docker build, not
  read at runtime. Pointing a deployed frontend at a different backend
  requires rebuilding the frontend image with a new
  `--build-arg REACT_APP_API_URL=...`.

### Persistence

Four named volumes carry state across container restarts:

| Volume | Mounted at | Contents |
|---|---|---|
| `index_data` | `/app/backend/index` | Hybrid value index, MDL cache, knowledge graph JSON |
| `rag_embed` | `/app/data/rag/embedding` | FAISS index + metadata JSONL |
| `logs_data` | `/app/observability/logs` | `audit.log`, `hallucination_traces.jsonl` |
| `auth_db` | `/app/auth` | SQLite `users.db` |

Without these, every `docker compose up` would rebuild the index from
Databricks from scratch and lose the auth database and logs on restart.

### Optional S3 cold-start sync

`docker/entrypoint.sh` runs before the FastAPI server starts:

```bash
INDEX_S3_URI=s3://your-bucket/index/           # syncs into $INDEX_DIR
RAG_EMBED_S3_URI=s3://your-bucket/rag/embedding/  # syncs into $RAG_EMBED_DIR
```

If either is set, `aws s3 sync` pulls a pre-built index/embedding set
before the app starts — useful for a fresh host that shouldn't have to
rebuild the Databricks index or re-embed the RAG corpus from scratch.
Requires the host to have AWS credentials (an EC2 instance IAM role with
`s3:GetObject`/`s3:ListBucket`, per the comment in `.env.example` — this
implies the intended deployment target is a single EC2 instance, not a
container platform with its own credential injection).

## Environment variables

`.env` (repo root, read by both the Docker build's `env_file` and local
`uvicorn`/`npm` runs) — see `.env.example` for the full annotated
template. The ones that matter operationally:

| Variable | Required | Notes |
|---|---|---|
| `DATABRICKS_SERVER_HOSTNAME` / `_HTTP_PATH` / `_TOKEN` | Yes | PAT-based auth; the token expires and must be regenerated manually (see `README.md`) |
| `DATABRICKS_CATALOG` / `_SCHEMA` | Yes | Defaults to `default` schema if unset |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` | At least one | Whichever LLM providers `llm_registry.py` is configured to use |
| `AUTH_SECRET_KEY` | **Yes in production** | See [Security considerations](#security-considerations) below — there is a hardcoded fallback if this is unset |
| `RAG_EMBED_DIR` / `RAG_EMBED_MODEL` | Yes for RAG | Must point at a real directory with matching `embeddings_<model>_2.{index,jsonl}` files — see `docs/knowledge_prep_design.md` for the filename convention |
| `INDEX_DIR` | No | Defaults to `backend/index`; Docker sets it to `/app/backend/index` explicitly |
| `AUDIT_LOG_DIR` | No | Defaults to `observability/logs/` |
| `UVICORN_WORKERS` | No | Defaults to 1 locally, 2 in `.env.example`; only `entrypoint.sh` (Docker) reads it — local `uvicorn --reload` always runs single-worker |
| `INDEX_S3_URI` / `RAG_EMBED_S3_URI` | No | See S3 cold-start sync above |
| `REACT_APP_API_URL` | Yes for frontend build | Build-time only, see note above |

## Security considerations

- **`AUTH_SECRET_KEY` fallback is a real risk, not a theoretical one.**
  `auth/auth_service.py` falls back to a hardcoded string
  (`"dev-secret-change-in-production-please"`) when `AUTH_SECRET_KEY`
  isn't set. Since that fallback is committed in plaintext in the source,
  anyone who has read the code can forge valid auth tokens against a
  deployment that forgot to set this variable. The current `.env` does
  **not** set it — this must be set before any deployment that isn't
  purely local/single-user.
- Demo accounts (`admin/admin123`, `alice/alice123`, `bob/bob123`,
  `carol/carol123`) are seeded automatically on first run
  (`auth_service.py`) — fine for local dev, but should be rotated or
  disabled for any shared deployment.
- `nginx.conf` serves plain HTTP on port 80 — no TLS termination is
  configured. A production deployment needs a reverse proxy or load
  balancer in front for HTTPS (the `.env.example` comment about an "ALB
  URL" suggests this was the intended pattern, but the ALB/TLS layer
  itself isn't part of this repo).
- CORS is wide open — `agent.py` sets
  `allow_origins=["*"], allow_credentials=True` — acceptable for a
  same-network internal tool, worth tightening if exposed publicly.

## Known gaps

- No CI/CD — builds and deploys are manual (`docker compose up --build`
  on the host).
- No orchestration beyond `docker compose` on a single host — no
  auto-restart-on-host-reboot config, no rolling updates, no horizontal
  scaling (the FastAPI backend *can* run multiple `UVICORN_WORKERS`, but
  that's process-level concurrency on one host, not multiple hosts).
- No automated backup of the named volumes (`auth_db`, `index_data`,
  `rag_embed`, `logs_data`) — losing the Docker host loses all of them
  unless S3 sync is configured for the index/embeddings.
