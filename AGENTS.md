# Repository Guidelines

## Mission Profile
- Codename: **Memscend** – multi-tenant memory ingestion + retrieval via OpenRouter ➜ TEI ➜ Qdrant.
- Output surfaces: HTTP REST/SSE gateway (`http_gw/`) and MCP tool server (`mcp_gw/`).
- Hard guardrails: enforce `org_id` + `agent_id` on every request, keep embedding dimensions consistent (default 768), no observability stack yet.

## Core Assets & Responsibilities
- `core/services.py` – orchestrates add/search/update/delete, resolves tenant overrides, manages Qdrant repositories. Touch with extreme care; preserve dedupe + time-decay logic.
- `core/clients/` – `openrouter.py` (LLM normalization), `tei.py` (embeddings). Respect retry/backoff semantics; MCP runs with `transport="sse"` and serves `/sse`.
- TEI client auto-falls back to deterministic embeddings when TEI is unreachable; OpenRouter client returns raw snippets on failure but keep normalization enabled when keys work.
- `core/storage/qdrant_repository.py` – Qdrant CRUD layer; ensure payloads include `text`, `dedupe_hash`, timestamps.
- `core/security.py` – shared-secret/JWT validation and tenancy reconciliation.
- `http_gw/app.py` – FastAPI routes mapping HTTP verbs to `MemoryCore`; handles SSE/NDJSON streaming.
- `mcp_gw/server.py` – FastMCP tool definitions mirroring HTTP behaviors.
- `infra/docker-compose.yaml` – Compose stack (TEI, Qdrant, gateways, optional `bundled-nginx` profile). Treat Nginx as local-only.
- `config/memory-config.yaml` – Default runtime config; hierarchy `global → org → agent`.

## Command Matrix
- Install deps: `uv sync`
- Format/lint: `uv run ruff format` + `uv run ruff check --fix`
- Unit & integration tests: `uv run pytest`
- Spin up deps only: `docker compose -f infra/docker-compose.yaml --env-file .env up --build tei-embed qdrant`
- Full local stack sans nginx: `docker compose -f infra/docker-compose.yaml --env-file .env up --build tei-embed qdrant http-gw mcp-gw`
- Optional proxy: `docker compose -f infra/docker-compose.yaml --env-file .env --profile bundled-nginx up nginx`
- Core bootstrap (creates collection): `uv run python scripts/bootstrap_qdrant.py`

## Configuration & Secrets
- `.env` supplies `OPENROUTER_API_KEY`, `HUGGING_FACE_HUB_TOKEN`, `MEMORY_SHARED_SECRET`.
- TEI container uses image `ghcr.io/huggingface/text-embeddings-inference:cpu-1.8` and expects `HF_TOKEN`; license acceptance for EmbeddingGemma is mandatory.
- Environment overrides: `TEI_BASE_URL`, `QDRANT_URL`, `OPENROUTER_BASE_URL`, `MEMORY_CONFIG_FILE`.
- Tenancy config lives under `core.organisations` in YAML; agent overrides inherit org values.
- Embedding dims allowed: `{128, 256, 512, 768}`. Changing dims requires new Qdrant collection.
- `core.write.normalize_with_llm` defaults `false` for offline builds; repository config enables it with `openrouter/sonoma-sky-alpha` once keys are present.
- Watch for OpenRouter `404` (privacy toggle missing) and `429` (upstream rate limit); fall back logic should prevent crashes but log the cause.

## HTTP Contract Cheatsheet
- Auth: `Authorization: Bearer <shared secret>` (or JWT), headers `X-Org-Id`, `X-Agent-Id` mandatory unless disabled.
- `POST /api/v1/mem/add` body: `user_id`, `text` or `messages[]`, optional `scope/tags/idempotency_key/ttl_days`.
- `GET /api/v1/mem/search` query: `q`, optional `user_id/k/scope/tags[]`.
- Streaming variants: `/search/ndjson` (NDJSON) and `/search/stream` (SSE, ping=20s).
- `PATCH /api/v1/mem/{id}` accepts partial updates (`text`, `tags`, `scope`, `ttl_days`, `deleted`).
- `DELETE /api/v1/mem/{id}` with `?hard=true` for physical delete; defaults to soft delete.

## MCP Tooling
- Tools: `add_memories`, `search_memory`, `update_memory`, `delete_memory` (structured responses match the HTTP gateway schema).
- Identity contract:
  - `org_id` + `agent_id` are mandatory for every tool call. Supply them explicitly or ensure the client can respond to elicitation prompts. Values persist per MCP session.
  - `user_id` is required for writes. Provide it up front; elicitation kicks in only if the client has advertised support.
  - If the client lacks elicitation, calls must include the IDs or the server raises a `ToolError` instructing the user to configure headers/arguments.
- Cached identity lives on the MCP session; reconnect when switching tenants or users.
- Startup/shutdown hooks call `MemoryCore.startup/shutdown`; avoid blocking operations inside tool handlers.
- Register server via MCP client config pointing at `http://127.0.0.1:8050`. SSE endpoint `/sse` (heartbeat 15 s); set `MCP_TRANSPORT=stdio` or `streamable_http` when using alternative transports.
- Recommended headers for HTTP/SSE clients that can set them: `X-Memscend-Org`, `X-Memscend-Agent`, `X-Memscend-User`.
- LLM normalization prompt (OpenRouter) expects JSON array objects `{memory, scope, confidence, language, skip}`. Enforce schema adherence; treat `skip=true` as discard. Malformed JSON triggers fallback to raw text—assume no guarantees about cleanup when upstream models misbehave.

## Testing Doctrine
- Pytest structure: `tests/unit/` (isolated with stubs), `tests/integration/` (FastAPI TestClient + patched core).
- Target coverage ≥80% on `core/`. Add tests for tenancy isolation, dedupe, time decay when modifying related logic.
- Mock external clients (`OpenRouterClient`, `TEIClient`, `QdrantRepository`) in unit tests; avoid real network IO.

## Deployment Playbook (VPS)
1. `uv sync`
2. `docker compose -f infra/docker-compose.yaml --env-file .env up -d tei-embed qdrant`
3. `uvicorn http_gw.app:app --host 0.0.0.0 --port 8080`
4. `python -m mcp_gw.server --host 0.0.0.0 --port 8050`
5. Host-level Nginx proxies `/api/` ➜ 8080, `/mcp/` ➜ 8050 (TLS enforced externally).
6. Keep `bundled-nginx` disabled in production.

## High-Risk Areas & Invariants
- Never loosen tenancy checks (`core/security.py`, `http_gw/app.py`, `mcp_gw/server.py`).
- Preserve dedupe hash computation (`core/utils.py`) and ensure upserts always include `dedupe_hash` in payload.
- Do not modify TEI/OpenRouter retry policies without updating failure modes in docs/runbook.
- Any change to vector size or collection names must propagate to `config`, compose env vars, and migration scripts.
- Observability intentionally absent; avoid introducing logging dependencies unless requirement changes.

## Reference Docs
- Product context: `docs/prd.md`
- Architecture blueprint: `docs/blueprint.md`
- Task sheet & milestones: `docs/task_sheet.md`
- Runbook stub: `docs/runbook.md` (extend when observability lands)

## Interaction Etiquette
- Prefer `apply_patch` for edits; maintain ASCII encoding.
- Respect existing TODO: observability deferred (“fuck observability for now”).
- When adding modules, colocate tests in matching `tests/...` path and update this guide.
