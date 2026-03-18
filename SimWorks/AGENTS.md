# AGENT INSTRUCTIONS — SimWorks Django scope

## Scope

Applies to `SimWorks/` and subdirectories unless overridden by a deeper `AGENTS.md`.

## Use with root guidance

- Read root `AGENTS.md` first, then shared docs in `docs/agents/`.
- This file only defines Django-app-local constraints.

## Local non-negotiables

- API contract: REST/OpenAPI for `/api/v1/` via Django Ninja.
- No GraphQL additions.
- UI direction: server-rendered templates + HTMX + Alpine.
- WebSocket messages are hints; clients must catch up via API.
- Side-effects/events must use outbox pattern.
- Propagate `X-Correlation-ID` through request, tasks, logs, and events.

## Local workflow

- Use `uv run` for Django commands (e.g., `uv run python manage.py migrate`).
- Prefer targeted `uv run pytest` for changed app areas.
- When models change, create and commit migrations.

## Local documentation expectations

- Keep product-facing docs aligned with MedSim naming.
- Keep architecture/API details aligned with `docs/agents/architecture-and-boundaries.md` and `docs/WEBSOCKET_EVENTS.md`.
