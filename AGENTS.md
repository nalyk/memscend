# Repository Guidelines

## Project Structure & Module Organization
Keep domain logic inside `core/`, which wraps OpenRouter, TEI, and Qdrant integrations. HTTP adapters live in `http_gw/` (FastAPI REST + streaming) and MCP tooling in `mcp_gw/`. Container and deployment assets belong in `infra/` (Compose, optional bundled Nginx, deployment scripts). Reference material stays in `docs/`. Add new modules only when they serve a tenant-aware memory capability; colocate tests alongside the code they cover.

## Build, Test, and Development Commands
Use `docker compose -f infra/docker-compose.yaml up --build tei-embed qdrant` to start local dependencies. Run the core service with `uv run python -m core.app` and the HTTP gateway with `uv run fastapi dev http_gw/app.py`. Execute the MCP server via `uv run python -m mcp_gw.server`. Smoke-test everything through `uv run pytest` before opening a PR. Prefer `make` wrappers only if they thinly proxy those commands.

## Coding Style & Naming Conventions
Python code targets 3.12, uses 4-space indentation, type hints, and docstrings on public functions. Follow the hexagonal boundary: orchestrators in `core/services.py`, repositories in `core/storage/`, and DTOs under `core/models.py`. Run `ruff check --fix` and `ruff format` before commits. Config files adopt lowercase-with-dashes (e.g., `memory-config.yaml`); environment variables use `UPPER_SNAKE_CASE`.

## Testing Guidelines
Structure tests under `tests/unit/` and `tests/integration/`; name files `test_*.py`. Use `pytest` fixtures to spin up TEI and Qdrant mocks, and mark network-dependent suites with `@pytest.mark.integration`. Target ≥80% coverage on core services and validate tenancy isolation scenarios. Run `uv run pytest --maxfail=1` locally and ensure GitHub workflows stay green.

## Commit & Pull Request Guidelines
Write commits in imperative mood with a concise scope tag, e.g., `core: enforce vector size guard`. Group related changes into a single commit when practical. Pull requests must describe intent, list validation steps (commands, datasets), and link the relevant task sheet item. Add screenshots or logs when touching observability, and request review from domain owners of the affected module.

## Security & Configuration Tips
Never commit API keys or Hugging Face tokens; load them via `.env` files ignored by Git. Validate `X-Org-Id`/`X-Agent-Id` headers at every entry point and include regression tests when adding new filters. When editing `infra/`, keep TLS defaults strict and document any change to rate limiting or retention in `docs/runbook.md`; enable the bundled Nginx profile only for local tests because production VPS deployments should rely on the host Nginx config.
