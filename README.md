# Memscend

Memscend is a multi-tenant memory service that extracts durable memories with a remote LLM (OpenRouter), embeds them locally with Text Embeddings Inference (TEI), and stores them in Qdrant for fast semantic retrieval. It exposes the same core logic via an HTTP API (REST + streaming) and an MCP server so IDE/agent clients can plug in with minimal glue code.

## Feature Highlights

- **Tenant-aware ingestion & search** – strict `org_id`/`agent_id` scoping, idempotent writes, optional dedupe, and time-decayed rankings.
- **Dual interfaces** – FastAPI gateway for REST/SSE/NDJSON plus an MCP SSE server offering `add/search/update/delete` tools.
- **Pluggable backends** – OpenRouter for extraction, TEI + `google/embeddinggemma-300m` for embeddings, Qdrant for vector storage with Matryoshka-friendly sizing.
- **Composable deployment** – Docker Compose bundle for TEI, Qdrant, gateways, and an optional Nginx reverse proxy; works on a CPU-only VPS.

## Repository Layout

```
├── core/            # Memory orchestration, clients, config, security, storage adapters
├── http_gw/         # FastAPI application (REST/SSE)
├── mcp_gw/          # FastMCP server exposing memory tools
├── infra/           # Dockerfile, compose stack, optional nginx config
├── config/          # Default YAML config (`memory-config.yaml`)
├── scripts/         # Helper scripts (bootstrap Qdrant collections)
├── tests/           # Unit & integration tests (pytest)
└── docs/            # PRD, blueprint, task sheet, runbook stubs
```

## Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) or virtualenv + pip (commands below use `uv`)
- Docker & Docker Compose (for TEI/Qdrant and optional bundled services)
- OpenRouter API key and Hugging Face token (accept the EmbeddingGemma license)
- Existing VPS Nginx is assumed for production; bundled proxy is only for local tests

## Configuration

1. Copy `.env.example` to `.env` and populate:
   - `OPENROUTER_API_KEY`
   - `HUGGING_FACE_HUB_TOKEN`
   - `MEMORY_SHARED_SECRET` (used by gateways for shared-secret auth)
2. Inspect `config/memory-config.yaml`:
   - Global write/retrieval policies (`core.write`, `core.retrieval`)
   - Default collection settings (vector size 768, cosine metric)
   - Tenant overrides (`core.organisations[<org_id>]` → per-agent overrides)
3. Environment overrides: set `TEI_BASE_URL`, `QDRANT_URL`, `OPENROUTER_BASE_URL`, etc. when services are not on defaults.

## Local Development Workflow

```bash
# Install dependencies
uv sync

# Bring up embeddings + vector DB
docker compose -f infra/docker-compose.yaml up --build tei-embed qdrant

# Run the HTTP gateway (REST/SSE)
uv run fastapi dev http_gw/app.py

# Run the MCP server in another shell (optional)
uv run python -m mcp_gw.server
```

Once the services are live, authenticate with `Authorization: Bearer <MEMORY_SHARED_SECRET>` and headers `X-Org-Id` / `X-Agent-Id` to interact.

## API Overview

- `POST /api/v1/mem/add` – ingest text/messages into tenant-scoped memory.
- `GET  /api/v1/mem/search` – JSON response of top-k hits.
- `GET  /api/v1/mem/search/ndjson` – streaming NDJSON hits.
- `GET  /api/v1/mem/search/stream` – SSE stream (heartbeat every 20s).
- `PATCH /api/v1/mem/{id}` – update text, tags, scope, TTL, soft-delete flag.
- `DELETE /api/v1/mem/{id}` – soft delete by default, `?hard=true` for permanent removal.

All endpoints require tenancy headers plus shared-secret (or JWT, if configured).

## MCP Tools

The FastMCP server exposes four tools over SSE (Claude Desktop, Cursor, etc.):

- `add_memories(text, user_id, org_id, agent_id, scope?, tags?, ttl_days?)`
- `search_memory(query, org_id, agent_id, user_id?, k?, scope?, tags?)`
- `update_memory(memory_id, org_id, agent_id, text?, tags?, scope?, ttl_days?, deleted?)`
- `delete_memory(memory_id, org_id, agent_id, hard?)`

Launch with `uv run python -m mcp_gw.server` and register the local server inside your MCP-compatible client.

## Docker Compose Stack

The compose bundle provides:

- `tei-embed` – Hugging Face TEI with EmbeddingGemma 300M (CPU)
- `qdrant` – vector database with on-disk payloads enabled
- `http-gw` – FastAPI gateway container
- `mcp-gw` – MCP server container
- `nginx` – optional reverse proxy (enable via profile `bundled-nginx`)

Run everything (without nginx) for local testing:

```bash
docker compose -f infra/docker-compose.yaml up --build tei-embed qdrant http-gw mcp-gw
```

To include the bundled proxy:

```bash
docker compose -f infra/docker-compose.yaml --profile bundled-nginx up nginx
```

## Production Reverse Proxy

Keep using your VPS-level Nginx. Point upstreams at the containers (or processes) listening on 8080 and 8050. Example TLS-ready snippet:

```nginx
upstream memscend_http { server 127.0.0.1:8080; }
upstream memscend_mcp  { server 127.0.0.1:8050; }

server {
    listen 443 ssl;
    server_name memscend.example.com;

    location /api/ { proxy_pass http://memscend_http; proxy_set_header Host $host; }
    location /mcp/ { proxy_pass http://memscend_mcp;  proxy_set_header Host $host; }
}
```

## Testing

- Unit + integration tests: `uv run pytest`
- Coverage goal: ≥80% on `core/`
- Tests rely on mocks (no live TEI/Qdrant/OpenRouter usage during unit tests)
- Run `ruff check --fix` and `ruff format` pre-commit

## Deployment Checklist (VPS)

1. Install Python 3.12, uv, Docker, and docker compose plugin.
2. Clone the repository and run `uv sync`.
3. Copy `.env.example` → `.env` with production credentials.
4. Start TEI + Qdrant via compose (or managed services if preferred).
5. Run `uv run python -m core.app` once (optional) to bootstrap collections, or execute `python scripts/bootstrap_qdrant.py`.
6. Use `uvicorn http_gw.app:app --host 0.0.0.0 --port 8080` under systemd/supervisor.
7. Launch MCP server (`python -m mcp_gw.server --host 0.0.0.0 --port 8050`) if MCP clients are required.
8. Configure your host Nginx with TLS + upstreams.
9. Verify with `uv run pytest` and a manual smoke test (`curl` or Postman) before exposing publicly.

## Troubleshooting

- **Missing dependencies:** install `pip install -e .[dev]` or use `uv sync` to ensure `pydantic>=2` and `qdrant-client` are available.
- **TEI cold start:** first request may take up to 30s; hitting `/v1/embeddings` on boot can warm it up.
- **Vector size mismatch:** ensure all tenants share the same embedding dimensions; otherwise create separate collections via overrides.
- **SSE behind proxies:** configure proxy timeouts ≥300s and enable bundled Nginx profile for local validation.

## Further Reading

- [`docs/prd.md`](docs/prd.md) – Product requirements
- [`docs/blueprint.md`](docs/blueprint.md) – Technical blueprint
- [`docs/task_sheet.md`](docs/task_sheet.md) – Implementation breakdown

Observability and advanced analytics are intentionally deferred (per initial scope: "fuck observability for now").
