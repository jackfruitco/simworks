# AGENT INSTRUCTIONS — SimWorks Django project

## Scope
These instructions apply to the Django project in `SimWorks/` and any subdirectories unless a deeper `AGENTS.md` overrides them.

## Architecture Direction (API v1)

**Non-negotiable decisions** — do not deviate from these:

1. **REST API + OpenAPI**: Use Django Ninja for `/api/v1/` endpoints. OpenAPI schema generated from code. No hand-authored specs.

2. **No GraphQL**: Strawberry GraphQL is being removed. Do not add GraphQL types, queries, mutations, or subscriptions.

3. **HTMX + Alpine for Web UI**: Keep server-rendered templates with HTMX for fragments and Alpine.js for lightweight client behavior. No React/Vue/Angular.

4. **WebSocket for hints only**: One WS per simulation (`/ws/simulation/{id}/`). WS messages are hints — clients must catch up via API.

5. **Outbox pattern for durability**: Side-effects (WS broadcasts, webhooks) go through `OutboxEvent` model. Drain worker delivers.

6. **Correlation ID everywhere**: All HTTP requests get `X-Correlation-ID`. Propagate to logs, tasks, WS events, spans.

## Development Workflow

- Use `uv run` for management commands (e.g., `uv run python manage.py migrate`, `uv run python manage.py runserver`).
- Prefer `uv run pytest` for test execution; target specific apps or tests when possible.
- When changing models, run `uv run python manage.py makemigrations` and include generated migration files.

## API Development

**Creating new endpoints:**
```python
# SimWorks/api/v1/endpoints/messages.py
from ninja import Router
from ninja.security import django_auth
from pydantic import BaseModel

router = Router(tags=["messages"])

class MessageOut(BaseModel):
    id: int
    content: str
    created_at: datetime

@router.get("/{simulation_id}/messages/", response=list[MessageOut])
def list_messages(request, simulation_id: int, after: str | None = None, limit: int = 50):
    """List messages for a simulation with cursor-based pagination."""
    # Implementation
```

**Authentication:**
- Web: Use `auth=django_auth` (session cookies)
- Mobile: Use custom JWT auth class

**Error responses:**
- Use RFC 7807 format with `correlation_id`
- Raise `HttpError` or return structured error dicts

## WebSocket Development

**Event envelope format** (all events must follow this):
```python
{
    "event_id": str(uuid4()),
    "created_at": datetime.now(UTC).isoformat(),
    "simulation_id": str(simulation_id),
    "type": "message.created",  # or typing.started, etc.
    "correlation_id": correlation_id or None,
    "payload": {...}
}
```

**Sending events** — always use the outbox:
```python
from core.outbox import enqueue_event

await enqueue_event(
    event_type="message.created",
    simulation_id=simulation_id,
    payload={"message_id": message.id},
    correlation_id=correlation_id,
)
```

## Coding Guidance

- Keep Django settings changes minimal and environment-agnostic; prefer environment variables.
- Favor explicit imports and avoid side effects at import time.
- Maintain consistent formatting for templates and static assets.
- Use Pydantic schemas for API request/response validation (not Django forms for API).
- Keep ORM models separate from API schemas — never expose ORM models directly.

## Testing Requirements

New code must include tests for:
- API endpoint behavior (request/response, auth, errors)
- WebSocket envelope correctness
- Outbox event creation and idempotency
- Correlation ID propagation

Use fixtures from `conftest.py` for common objects (users, simulations, messages).

## Documentation

- Update `CLAUDE.md` "API Contracts" section when adding new endpoints or changing event formats.
- Include OpenAPI examples in endpoint docstrings.
- Keep `docs/` up to date with architectural decisions.

## Things to Avoid

- Do not add GraphQL schemas, types, or resolvers
- Do not use `channel_layer.group_send()` directly — use the outbox
- Do not add React, Vue, or other SPA frameworks
- Do not bypass correlation ID middleware
- Do not create new WS connections per message — one per simulation
