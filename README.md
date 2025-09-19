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

2. Visit the model pages and accept license terms:
   - <https://huggingface.co/google/embeddinggemma-300m>
   - <https://openrouter.ai/models/openrouter/sonoma-sky-alpha>
3. Inspect `config/memory-config.yaml`:
   - Global write/retrieval policies (`core.write`, `core.retrieval`)
   - Default collection settings (vector size 768, cosine metric)
   - Tenant overrides (`core.organisations[<org_id>]` → per-agent overrides)
   - `core.write.normalize_with_llm` defaults to `false` so the service runs without OpenRouter; set to `true` when a valid key is configured. This repo ships with it enabled using `openrouter/sonoma-sky-alpha`.
4. Environment overrides: set `TEI_BASE_URL`, `QDRANT_URL`, `OPENROUTER_BASE_URL`, etc. when services are not on defaults.

## Policy Playbooks

Memscend derives write/search behaviour from the defaults in `core.write` / `core.retrieval` and the overrides defined under `core.organisations`. The scenarios below capture common agent personas; drop the snippets into `config/memory-config.yaml` (or environment-specific overrides) and adjust IDs to match your tenants.

### Personal assistant (long-lived habits)

```yaml
core:
  organisations:
    home:
      agents:
        pa:
          write:
            enabled_scopes: ["facts", "prefs", "persona", "constraints"]
            normalize_with_llm: true
            min_chars: 12
            deduplicate: true
            max_batch: 16
          retrieval:
            top_k: 8
            ef_search: 96
            include_text: true
```

- Capture routines, commitments, and style cues; keep every scope enabled so preferences and persona traits persist.
- Leave normalization on so OpenRouter cleans messy snippets and honours `skip=true` responses.
- Slightly higher `top_k`/`ef_search` keeps older memories searchable when the account accrues thousands of entries.

### Pair-programming buddy (ephemeral code context)

```yaml
core:
  organisations:
    studio:
      agents:
        dev-buddy:
          write:
            enabled_scopes: ["facts", "constraints"]
            normalize_with_llm: false
            min_chars: 24
            deduplicate: true
          retrieval:
            top_k: 4
            include_text: true
```

- Scope down to design decisions and guardrails; skip persona/prefs to avoid overfitting on teammate chatter.
- Disable normalization so code fragments and stack traces are stored verbatim; the higher `min_chars` filters drive-by comments.
- Ask the client to set `ttl_days` (7–14) on writes so outdated branch notes expire automatically.

### Support triage agent (multi-user tickets)

```yaml
core:
  organisations:
    support:
      write:
        enabled_scopes: ["facts", "constraints"]
        normalize_with_llm: true
        min_chars: 18
        deduplicate: true
        max_batch: 8
      retrieval:
        top_k: 6
        ef_search: 128
        include_text: true
```

- Normalization standardises noisy ticket summaries while dedupe prevents duplicate escalation records.
- Lower `max_batch` keeps bursty ingest (e.g. nightly sync jobs) from flooding Qdrant; push `ttl_days` ≈30 when creating memories so aged tickets fall away.
- Higher `ef_search` boosts recall across similar incidents reported by different users or regions.

### Project memory hub (research notes and decisions)

```yaml
core:
  organisations:
    research:
      write:
        enabled_scopes: ["facts", "constraints"]
        normalize_with_llm: true
        min_chars: 32
        deduplicate: false
      retrieval:
        top_k: 10
        include_text: true
```

- Allow richer notes by relaxing dedupe; multiple meeting summaries can coexist without overwriting one another.
- Encourage clients to tag entries with project IDs and to set `ttl_days` when initiatives sunset.
- Larger `top_k` supports comparative research (“what did we decide last quarter?”) where multiple memos matter.

**Cross-cutting tips**
- Define separate `core.organisations` entries per tenant; shared defaults risk accidental data mixing.
- Keep embedding dimensions aligned (128/256/512/768) and recreate collections when you change them.
- Treat `max_batch` as backpressure—raise it only after verifying Qdrant latency under load.
- Leave `deduplicate` enabled unless you explicitly need near-duplicate tracking (e.g. iterative drafts).
- Clients must still send `tags` and `ttl_days`; policies cannot infer lifecycle metadata automatically.

Lightweight policy tuning like this mirrors guidance from the OpenAI Cookbook vector database notes and Pinecone’s production memory recommendations, while staying within Memscend’s tenancy guardrails.

## Local Development Workflow

```bash
# Install dependencies
uv sync

# Bring up embeddings + vector DB (requires .env)
docker compose -f infra/docker-compose.yaml --env-file .env up --build tei-embed qdrant

# Run the HTTP gateway (REST/SSE)
uv run fastapi dev http_gw/app.py

# Run the MCP server in another shell (optional)
uv run python -m mcp_gw.server
```

Once the services are live, authenticate with `Authorization: Bearer <MEMORY_SHARED_SECRET>` and headers `X-Org-Id` / `X-Agent-Id` to interact. Without TEI or OpenRouter credentials the service falls back to deterministic stub embeddings and raw text (for testing only).

## API Overview

- `POST /api/v1/mem/add` – ingest text/messages into tenant-scoped memory.
- `GET  /api/v1/mem/search` – JSON response of top-k hits.
- `GET  /api/v1/mem/search/ndjson` – streaming NDJSON hits.
- `GET  /api/v1/mem/search/stream` – SSE stream (heartbeat every 20s).
- `PATCH /api/v1/mem/{id}` – update text, tags, scope, TTL, soft-delete flag.
- `DELETE /api/v1/mem/{id}` – soft delete by default, `?hard=true` for permanent removal.
- `GET  /api/v1/mem/list` – list recent memories for the current tenant.
- `GET  /api/v1/mem/search/text` – substring search across stored memory text.
- `POST /api/v1/mem/open` – fetch memories by ID.
- `POST /api/v1/mem/delete/batch` – delete multiple memories (soft or hard).

All endpoints require tenancy headers plus shared-secret (or JWT, if configured).

## MCP Tools

The FastMCP server exposes structured tools (Pydantic responses) with context-aware logging and progress. Highlights:

- `add_memories(text?, messages?, user_id?, org_id?, agent_id?, scope?, tags?, ttl_days?, source?, idempotency_key?)`
- `search_memory(query, org_id?, agent_id?, user_id?, k?, scope?, tags?)`
- `update_memory(memory_id, org_id?, agent_id?, text?, tags?, scope?, ttl_days?, deleted?)`
- `delete_memory(memory_id, org_id?, agent_id?, hard?)`
- `list_memories(org_id?, agent_id?, limit?, include_deleted?)`
- `open_memories(memory_ids[], org_id?, agent_id?)`
- `delete_memories(memory_ids[], org_id?, agent_id?, hard?)`
- `search_memory_text(query, org_id?, agent_id?, limit?, include_deleted?)`

All tools emit rich JSON that mirrors the HTTP gateway schema. Clients also gain access to the read-only resource `memscend://capabilities` for static defaults (scopes, vector size, transports).

### Identity requirements

- `org_id` and `agent_id` remain mandatory for every call. If a client omits them and _does_ support [MCP elicitation](https://modelcontextprotocol.io/specification/draft/basic/elicitation), the server prompts once per session and caches the responses. Clients that do **not** implement elicitation must supply the identifiers via tool arguments or transport headers (for SSE/streamable HTTP).
- `user_id` is required for writes (`add_memories`, `update_memory`, `delete_memory`); the same hybrid behaviour applies—prompt when possible, otherwise raise an error.
- Cached values live for the lifetime of the MCP session. Reconnect when switching tenants or end users.

Tip: when using browser-based SSE transports, configure headers (e.g. `X-Memscend-Org`, `X-Memscend-Agent`, `X-Memscend-User`) through your client’s transport settings to avoid repeated prompts.

### LLM normalization

- When `core.write.normalize_with_llm` is enabled, snippets are sent to OpenRouter with a structured extraction prompt. The model must reply with a JSON array of entries `{memory, scope, confidence, language, skip}`. Entries flagged with `skip=true` are discarded; remaining `memory` strings populate the pipeline.
- If the model cannot follow the schema (malformed JSON, empty list) we fall back to the raw text so ingest never stalls.
- Provide multilingual-friendly models for best results; otherwise disable normalization to avoid lossy rewriting.

Launch with `uv run python -m mcp_gw.server` and register the local server inside your MCP-compatible client. The server binds to `0.0.0.0:8050` and exposes an SSE endpoint at `/sse` (keep-alive pings every 15 s). Set `MCP_TRANSPORT=stdio` or `MCP_TRANSPORT=streamable_http` to switch transports without code changes.

### Recommended agent prompt

For best results, prime your MCP client/agent with the following instructions before connecting to Memscend. They combine role prompting, retrieval planning, and self-checks aligned with our ingestion pipeline.

```
<mandatory_memory_protocol>
Follow these instructions for each interaction:

Global rules:
1. Identity & tenancy
   • Always operate for `org_id` = {{ORG_ID}} and `agent_id` = {{AGENT_ID}}.
   • Use `user_id` = {{USER_ID}} when known; if unknown, elicit it once and reuse.
   • If the MCP server prompts for missing IDs, answer immediately and cache them.

2. Interaction ritual (Observe → Recall → Decide → Act → Reflect)
   a. OBSERVE: Restate the user's latest request and any implicit goals in your private reasoning.
   b. RECALL: Announce "Remembering...", call `search_memory` (and optionally `list_memories` for a quick recent snapshot). Blend retrieved facts into context.
   c. DECIDE: Plan the next tool call(s). Prefer `search_memory`/`list_memories` before writing. Use `search_memory_text` or `open_memories` when you need exact matches.
   d. ACT: Respond to the user. Reference stored knowledge naturally ("According to my memory..."). Clarify before guessing.
   e. REFLECT (STORE): Track durable facts in these scopes:
        - facts: stable details, schedules, commitments
        - prefs: likes/dislikes, interaction style, language choices
        - persona: long-lived traits, roles, bios
        - constraints: obligations, limitations, forbidden items
      Use `add_memories` for new items, `update_memory` when a stored fact changes, and `delete_memory` when information is retracted.

3. Memory hygiene checklist (run mentally before calling `add_memories`)
   ▢ The information will matter beyond this moment (>=12 meaningful characters)
   ▢ It is not sensitive (no passwords, legal IDs, or negative gossip)
   ▢ It is expressed clearly in a single sentence (the server will normalize, but write cleanly)
   ▢ It does not duplicate an existing memory (confirm via `search_memory` hits)
   ▢ Language is the same as the user’s original wording unless a translation increases clarity—note translations explicitly

4. Update discipline
   • If the user corrects a previous fact, call `update_memory` on the original record rather than storing a second copy.
   • When information is no longer valid, call `delete_memory(hard=false)` to soft-delete; reserve `hard=true` for irreversible removals.

5. Memory hygiene checklist (run mentally before `add_memories`)
   ▢ ≥12 meaningful characters (not trivial chatter)
   ▢ Not sensitive (no passwords, legal IDs, or unverified gossip)
   ▢ Expressed as one precise sentence (the server will normalize but write cleanly)
   ▢ Not already present (verify via `search_memory`/`search_memory_text`)
   ▢ Stored in the user’s original language unless translation improves clarity—note translated content explicitly

6. Failure handling & maintenance
   • If a tool errors, surface the issue, remediate (supply missing IDs, retry later), and avoid silent failures.
   • When no durable memory exists, state "Nothing new to remember." and skip write calls.
   • Use `delete_memories` for bulk cleanup (soft by default). Escalate to `hard=true` only when retention is unacceptable.

7. Multilingual support
   • Store memories in the user’s language whenever possible.
   • If you translate, include qualifiers like "(originally in es)".

Stay concise, respect user privacy, and let the Memscend server manage deduplication, time decay, and normalization.
</mandatory_memory_protocol>
```

### MCP client configuration

Memscend exposes three transports:
- **SSE:** `http://<host>:8050/sse`
- **Streamable HTTP:** `http://<host>:8050/mcp`
- **STDIO:** run `python -m mcp_gw.server` (set `MCP_TRANSPORT=stdio` to force stdio)

Below are quick-start snippets for popular MCP clients.

#### Claude Desktop
- Claude Desktop speaks stdio. Bridge our SSE endpoint with the official proxy helper:
  ```bash
  uvx mcp-proxy --server-url http://<host>:8050/sse --client claude-desktop
  ```
  Keep the proxy running; Claude Desktop will list Memscend once the proxy registers.

#### Cursor IDE
- Cursor can connect over SSE via Settings → MCP:
  ```json
  {
    "type": "sse",
    "id": "memscend-memory",
    "url": "http://<host>:8050/sse",
    "description": "Memscend memory service"
  }
  ```
- Alternatively, configure a stdio command if you run the server locally inside the project environment.

#### Windsurf (Cascade)
- Enable MCP under **Settings → MCP** and register Memscend with the SSE URL above. Remote MCP servers require a paid Windsurf plan; local stdio connections remain available on free tiers.

#### JetBrains AI Assistant
- JetBrains 2025.2+ provides an MCP panel. Add Memscend as a custom stdio server:
  ```bash
  python -m mcp_gw.server --host 0.0.0.0 --port 8050
  ```
  Configure the command to run inside your project environment; the IDE handles stdio wiring automatically.

#### Streamable HTTP & other clients
- FastMCP-compatible clients that speak streamable HTTP can target `http://<host>:8050/mcp` directly.
- If a client cannot set headers for SSE, use `mcp-proxy` (shown above) to relay the connection.

Always supply `X-Org-Id` and `X-Agent-Id` (or respond to elicitation) so Memscend can scope memories correctly.

#### CLI agents
- **Claude Code CLI:** Add Memscend over SSE with headers so the CLI can authenticate without editing JSON files every time:
  ```bash
  claude mcp add --transport sse --scope local memscend \
    http://<host>:8050/sse \
    --header "Authorization: Bearer <shared secret>" \
    --header "X-Org-Id: <org_id>" \
    --header "X-Agent-Id: <agent_id>" \
    --header "X-Memscend-User: <user_id>"
  ```
  The CLI stores the entry in `~/.claude/settings.json` (or the project/local overrides listed in the Claude docs).[1][2]

- **OpenAI Codex CLI:** Codex only speaks stdio today, so point it at `mcp-proxy`, which bridges our SSE endpoint to codex-compatible stdio. Add the following block to `~/.codex/config.toml` (or create it if missing):
  ```toml
  [mcp_servers.memscend]
  command = "npx"
  args = [
    "-y", "mcp-proxy",
    "--server-url", "http://<host>:8050/sse",
    "--header", "Authorization: Bearer <shared secret>",
    "--header", "X-Org-Id: <org_id>",
    "--header", "X-Agent-Id: <agent_id>",
    "--header", "X-Memscend-User: <user_id>"
  ]
  ```
  Codex will launch the proxy on demand and stream tools through it.[7]

- **Gemini CLI:** Define a remote server in `~/.gemini/settings.json` (or `.gemini/settings.json` in your workspace):
  ```json
  {
    "mcpServers": {
      "memscend": {
        "url": "http://<host>:8050/sse",
        "headers": {
          "Authorization": "Bearer <shared secret>",
          "X-Org-Id": "<org_id>",
          "X-Agent-Id": "<agent_id>",
          "X-Memscend-User": "<user_id>"
        }
      }
    }
  }
  ```
  Gemini will pick up the change after a `/mcp refresh`.[3]

- **Qwen Code CLI:** Use the built-in helper to register our SSE endpoint:
  ```bash
  qwen mcp add --scope user --transport sse memscend http://<host>:8050/sse \
    --header "Authorization: Bearer <shared secret>" \
    --header "X-Org-Id: <org_id>" \
    --header "X-Agent-Id: <agent_id>" \
    --header "X-Memscend-User: <user_id>"
  ```
  The command writes to `~/.qwen/settings.json`; you can also edit the `mcpServers` block manually if you prefer.[4]

- **OpenCode CLI:** Add a `mcp` entry to `opencode.json` (either project-local or `~/.config/opencode/opencode.json`):
  ```json
  {
    "$schema": "https://opencode.ai/config.json",
    "mcp": {
      "memscend": {
        "type": "remote",
        "enabled": true,
        "url": "http://<host>:8050/sse",
        "headers": {
          "Authorization": "Bearer <shared secret>",
          "X-Org-Id": "<org_id>",
          "X-Agent-Id": "<agent_id>",
          "X-Memscend-User": "<user_id>"
        }
      }
    }
  }
  ```
  OpenCode ingests the config on restart; the same structure works in the global config under `~/.config/opencode/`.[5][6]

#### n8n workflows
- Install the community package `nerding-io/n8n-nodes-mcp` (requires `N8N_COMMUNITY_PACKAGES_ALLOW_TOOL_USAGE=true` in your n8n environment).
- In the MCP Client credentials, choose **SSE** and set `Endpoint` to `http://<host>:8050/sse`. Add custom headers for `Authorization: Bearer <MEMORY_SHARED_SECRET>`, `X-Org-Id`, and `X-Agent-Id`.
- To run Memscend locally for n8n’s MCP Client, point SIgnCommand/Arguments at `python -m mcp_gw.server` (stdio) or expose the SSE endpoint via Docker Compose for remote n8n instances.
- If the n8n MCP Client reports “No transport found,” restart the workflow and confirm the SSE endpoint is reachable in a browser—this clears stale sessions noted by n8n users.

#### Memscend Memory node for n8n
- Early WIP: the dedicated node is not functional yet; treat it as a placeholder until we ship a working build.
- A dedicated memory provider lives in [`packages/n8n-nodes-memscend-memory`](packages/n8n-nodes-memscend-memory). Build and publish it to n8n with:
  ```bash
  cd packages/n8n-nodes-memscend-memory
  npm install
  npm run build
  npm publish --access public  # when ready
  ```
- Install the package in n8n (requires `N8N_COMMUNITY_PACKAGES_ALLOW_TOOL_USAGE=true`), add the **Memscend API** credential, then drop the **Memscend Memory** node into the Agent’s memory slot.

## Docker Compose Stack

The compose bundle provides:

- `tei-embed` – Hugging Face TEI with EmbeddingGemma 300M (CPU)
- `qdrant` – vector database with on-disk payloads enabled
- `http-gw` – FastAPI gateway container
- `mcp-gw` – MCP server container
- `nginx` – optional reverse proxy (enable via profile `bundled-nginx`)

Run everything (without nginx) for local testing:

```bash
docker compose -f infra/docker-compose.yaml --env-file .env up --build tei-embed qdrant http-gw mcp-gw
```

To include the bundled proxy:

```bash
docker compose -f infra/docker-compose.yaml --env-file .env --profile bundled-nginx up nginx
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
- **TEI cold start / 401:** the `tei-embed` container (tag `cpu-1.8`) needs `HF_TOKEN`; if you see 401s, confirm the token has accepted EmbeddingGemma. Batch size is limited to 4 on CPU; the service adjusts automatically.
- **Vector size mismatch:** ensure all tenants share the same embedding dimensions; otherwise create separate collections via overrides.
- **SSE behind proxies:** configure proxy timeouts ≥300s and enable bundled Nginx profile for local validation.
- **OpenRouter 404/429:** 404 indicates the free/publication toggle isn’t enabled on OpenRouter; 429 means upstream rate limit—retry after a short pause.

## Further Reading

- [`docs/prd.md`](docs/prd.md) – Product requirements
- [`docs/blueprint.md`](docs/blueprint.md) – Technical blueprint
- [`docs/task_sheet.md`](docs/task_sheet.md) – Implementation breakdown

Observability and advanced analytics are intentionally deferred (per initial scope: "fuck observability for now").
