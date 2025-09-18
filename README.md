# Memory Service

Multi-tenant memory storage service backed by OpenRouter (LLM), Text Embeddings Inference, and Qdrant. See `docs/` for the full PRD, blueprint, and task sheet.

## Getting Started

1. Copy `.env.example` to `.env` and fill in provider tokens.
2. Launch dependencies (TEI + Qdrant):
   ```bash
   docker compose -f infra/docker-compose.yaml up --build tei-embed qdrant
   ```
3. Run the HTTP gateway locally:
   ```bash
   uv run fastapi dev http_gw/app.py
   ```
4. Optionally start the MCP server:
   ```bash
   uv run python -m mcp_gw.server
   ```

Use `uv run pytest` for the test suite.

## Reverse Proxy Options

- **Existing VPS Nginx (recommended):** point your host Nginx at the HTTP gateway (`http://127.0.0.1:8080`) and MCP server (`http://127.0.0.1:8050`). Example:
  ```nginx
  upstream memory_http { server 127.0.0.1:8080; }
  upstream memory_mcp  { server 127.0.0.1:8050; }

  server {
      listen 443 ssl;
      server_name memory.example.com;

      location /api/ { proxy_pass http://memory_http; proxy_set_header Host $host; }
      location /mcp/ { proxy_pass http://memory_mcp;  proxy_set_header Host $host; }
  }
  ```
- **Bundled Nginx (local testing):** the Compose file ships an optional proxy with sane SSE defaults. Start it with the profile flag:
  ```bash
  docker compose -f infra/docker-compose.yaml --profile bundled-nginx up nginx
  ```
  Adjust `infra/nginx/nginx.conf` before enabling it in production.
