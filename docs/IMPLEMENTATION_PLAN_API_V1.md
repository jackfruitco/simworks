# SimWorks API v1 Implementation Plan

This document outlines the phased implementation plan for migrating SimWorks to a REST-ish JSON API with OpenAPI, standardized WebSocket events, and the outbox pattern.

## Repo Review Summary

### Current State

**GraphQL (to be removed):**
- Dependencies: `strawberry-graphql-django==0.70.1`, `strawberry-graphql>=0.287.3`
- URL: `/graphql/` via `AsyncGraphQLView`
- Schemas: `accounts/schema.py`, `simcore/schema.py`, `chatlab/schema.py`, `trainerlab/schema.py`
- Middleware: `config/middleware.py` (RequireApiPermissionMiddleware)
- Frontend usage: Profile page link to GraphiQL, modifier selector in `_session_form.html`
- Tests: None found
- **Issue**: `modifierGroups` query called from frontend but not implemented in schema

**WebSockets (keep, standardize):**
- Consumers: `ChatConsumer` (chatlab), `NotificationsConsumer` (core)
- Routes: `/ws/simulation/{id}/`, `/ws/notifications/`
- Signal-based broadcasts via `post_save` on Message/SimulationMetadata
- Tests: `tests/chatlab/test_consumers.py` (comprehensive)

**HTMX + Alpine (keep):**
- HTMX: Fragment loading, form submissions, infinite scroll
- Alpine: Chat components, tool panels, toast notifications, filters
- Views return different templates based on `request.htmx`

**Background Tasks (extend with outbox):**
- Django Tasks framework with `AsyncThreadBackend`
- `ServiceCallRecord` for task state persistence
- Two-phase commit: execution → persistence
- Drain worker: `process_pending_persistence()`
- Idempotency via `PersistedChunk`

---

## Phase 1: Foundation (PR #1)

**Goal**: Set up Django Ninja, correlation ID middleware, and basic infrastructure.

### Tasks

1. **Add Django Ninja dependency**
   ```bash
   uv add django-ninja
   ```

2. **Create API app structure**
   ```
   SimWorks/
     api/
       __init__.py
       v1/
         __init__.py
         api.py           # Main NinjaAPI instance
         auth.py          # JWT auth classes
         schemas/         # Pydantic schemas
           __init__.py
           common.py      # Pagination, errors
         endpoints/
           __init__.py
   ```

3. **Create `CorrelationIDMiddleware`**
   - Location: `core/middleware.py`
   - Read `X-Correlation-ID` header, generate UUID if missing
   - Attach to `request.correlation_id`
   - Add to response headers
   - Add to Django `MIDDLEWARE`

4. **Create base error schemas**
   ```python
   # api/v1/schemas/common.py
   class ErrorResponse(BaseModel):
       type: str
       title: str
       status: int
       detail: str
       instance: str | None = None
       correlation_id: str | None = None
   ```

5. **Mount API at `/api/v1/`**
   ```python
   # config/urls.py
   from api.v1.api import api as api_v1
   urlpatterns = [
       path("api/v1/", api_v1.urls),
       # ... existing routes
   ]
   ```

6. **Tests**
   - `tests/api/test_correlation_id.py`: Middleware generates/propagates correlation ID
   - `tests/api/test_api_foundation.py`: API mounts correctly, returns 404 for unknown routes

### Files Changed
- `pyproject.toml` (add django-ninja)
- `SimWorks/core/middleware.py` (add CorrelationIDMiddleware)
- `SimWorks/config/settings.py` (add middleware)
- `SimWorks/config/urls.py` (mount API)
- `SimWorks/api/` (new directory)
- `tests/api/` (new tests)

---

## Phase 2: JWT Authentication (PR #2)

**Goal**: Implement JWT token auth for mobile clients.

### Tasks

1. **Add PyJWT dependency**
   ```bash
   uv add pyjwt
   ```

2. **Create JWT auth module**
   ```python
   # api/v1/auth.py
   from ninja.security import HttpBearer

   class JWTAuth(HttpBearer):
       def authenticate(self, request, token):
           # Verify JWT, return user or None

   def create_tokens(user) -> dict:
       # Return {access_token, refresh_token, expires_in}

   def refresh_access_token(refresh_token: str) -> dict:
       # Validate refresh, return new access token
   ```

3. **Create auth endpoints**
   ```python
   # api/v1/endpoints/auth.py
   @router.post("/token/", response=TokenResponse)
   def obtain_token(request, credentials: LoginRequest):
       ...

   @router.post("/token/refresh/", response=TokenResponse)
   def refresh_token(request, body: RefreshRequest):
       ...
   ```

4. **Settings**
   ```python
   # config/settings.py
   JWT_SECRET_KEY = env("JWT_SECRET_KEY", default=SECRET_KEY)
   JWT_ACCESS_TOKEN_LIFETIME = 3600  # 1 hour
   JWT_REFRESH_TOKEN_LIFETIME = 86400 * 7  # 7 days
   ```

5. **Tests**
   - Token generation and validation
   - Token refresh flow
   - Invalid token handling
   - Expired token handling

### Files Changed
- `pyproject.toml` (add pyjwt)
- `SimWorks/api/v1/auth.py` (new)
- `SimWorks/api/v1/endpoints/auth.py` (new)
- `SimWorks/config/settings.py` (JWT settings)
- `tests/api/test_jwt_auth.py` (new)

---

## Phase 3: Core API Endpoints (PR #3)

**Goal**: Implement essential API endpoints for simulations and messages.

### Tasks

1. **Simulation endpoints**
   ```python
   # api/v1/endpoints/simulations.py
   GET  /simulations/                    # List user's simulations
   GET  /simulations/{id}/               # Get simulation details
   POST /simulations/                    # Create new simulation
   POST /simulations/{id}/end/           # End simulation
   GET  /simulations/{id}/messages/      # List messages (cursor pagination)
   POST /simulations/{id}/messages/      # Send message
   GET  /simulations/{id}/events/        # List events (catch-up endpoint)
   ```

2. **Pagination schema**
   ```python
   class PaginatedResponse(BaseModel, Generic[T]):
       items: list[T]
       next_cursor: str | None
       has_more: bool
   ```

3. **Cursor-based pagination**
   - Use `event_id` (UUID) as opaque cursor
   - Query: `WHERE id > cursor_id ORDER BY id LIMIT limit+1`
   - If `len(results) > limit`: `has_more=True`, `next_cursor=results[limit-1].id`

4. **Message creation flow**
   - Validate user can access simulation
   - Create Message record
   - Enqueue AI response service
   - Return message with `202 Accepted` or `201 Created`

5. **Tests**
   - CRUD operations
   - Pagination edge cases
   - Authorization (user can only access own simulations)
   - Message creation triggers AI service

### Files Changed
- `SimWorks/api/v1/endpoints/simulations.py` (new)
- `SimWorks/api/v1/endpoints/messages.py` (new)
- `SimWorks/api/v1/schemas/simulations.py` (new)
- `SimWorks/api/v1/schemas/messages.py` (new)
- `tests/api/test_simulations.py` (new)
- `tests/api/test_messages.py` (new)

---

## Phase 4: Outbox Model & Drainer (PR #4)

**Goal**: Implement the outbox pattern for durable event delivery.

### Tasks

1. **Create OutboxEvent model**
   ```python
   # core/models.py
   class OutboxEvent(models.Model):
       id = models.UUIDField(primary_key=True, default=uuid.uuid4)
       idempotency_key = models.CharField(max_length=255, unique=True)
       event_type = models.CharField(max_length=100, db_index=True)
       payload = models.JSONField()
       simulation_id = models.CharField(max_length=100, db_index=True)
       correlation_id = models.CharField(max_length=100, null=True, blank=True)
       created_at = models.DateTimeField(auto_now_add=True, db_index=True)
       delivered_at = models.DateTimeField(null=True, db_index=True)
       delivery_attempts = models.PositiveIntegerField(default=0)
       last_error = models.TextField(null=True, blank=True)

       class Meta:
           indexes = [
               models.Index(fields=['delivered_at', 'created_at']),
               models.Index(fields=['simulation_id', 'created_at']),
           ]
   ```

2. **Create outbox helpers**
   ```python
   # core/outbox.py
   async def enqueue_event(
       event_type: str,
       simulation_id: str | int,
       payload: dict,
       correlation_id: str | None = None,
       idempotency_key: str | None = None,
   ) -> OutboxEvent:
       """Create outbox event atomically with domain changes."""

   def build_ws_envelope(event: OutboxEvent) -> dict:
       """Build WebSocket event envelope from OutboxEvent."""
   ```

3. **Create drain worker (hybrid mode)**
   ```python
   # core/tasks.py
   from django.tasks import task

   @task
   def drain_outbox():
       """Periodic task to deliver pending outbox events."""
       # select_for_update(skip_locked=True)
       # Batch process, deliver to WS
       # Mark delivered_at, handle errors

   async def poke_drain():
       """Immediate trigger for low-latency delivery."""
       # Called after event creation for immediate delivery
   ```

4. **Celery Beat schedule**
   ```python
   # config/celery.py
   app.conf.beat_schedule = {
       'drain-outbox': {
           'task': 'core.tasks.drain_outbox',
           'schedule': 15.0,  # Every 15 seconds
       },
   }
   ```

5. **Migrate signal handlers to outbox**
   - Update `chatlab/signals.py` to create OutboxEvent instead of direct `group_send`
   - Keep backwards compatibility during transition

6. **Tests**
   - Outbox event creation with idempotency
   - Drain worker processes pending events
   - Concurrent drain safety (skip_locked)
   - Error handling and retry
   - WS delivery via channel layer

### Files Changed
- `SimWorks/core/models.py` (add OutboxEvent)
- `SimWorks/core/outbox.py` (new)
- `SimWorks/core/tasks.py` (add drain_outbox)
- `SimWorks/config/celery.py` (beat schedule)
- `SimWorks/chatlab/signals.py` (migrate to outbox)
- Migration file
- `tests/core/test_outbox.py` (new)

---

## Phase 5: WebSocket Envelope Standardization (PR #5)

**Goal**: Standardize all WebSocket events to use the new envelope format.

### Tasks

1. **Update ChatConsumer**
   - Modify all `send()` calls to use envelope format
   - Add `event_id`, `created_at`, `correlation_id` to all events
   - Update event type names (e.g., `chat.message_created` → `message.created`)

2. **Update NotificationsConsumer**
   - Same envelope format for notification events

3. **Update drain worker delivery**
   - Use `build_ws_envelope()` for all outbox deliveries

4. **Client-side updates**
   - Update `chat.js` to handle new envelope format
   - Add deduplication by `event_id`
   - Add deduplication by `message_id` for message events

5. **Tests**
   - Envelope format validation
   - All event types have required fields
   - Client-side deduplication logic

### Files Changed
- `SimWorks/chatlab/consumers.py` (envelope format)
- `SimWorks/core/consumers.py` (envelope format)
- `SimWorks/chatlab/static/chatlab/js/chat.js` (client updates)
- `tests/chatlab/test_consumers.py` (update tests)
- `tests/api/test_ws_envelope.py` (new)

---

## Phase 6: GraphQL Removal (PR #6)

**Goal**: Remove all GraphQL code from the codebase.

### Tasks

1. **Remove dependencies**
   ```bash
   uv remove strawberry-graphql-django strawberry-graphql
   ```

2. **Remove URL route**
   - Delete `/graphql/` from `config/urls.py`

3. **Remove schema files**
   - `config/schema.py`
   - `accounts/schema.py`
   - `simcore/schema.py`
   - `chatlab/schema.py`
   - `trainerlab/schema.py`

4. **Remove middleware**
   - `RequireApiPermissionMiddleware` from `config/middleware.py`
   - Remove from `MIDDLEWARE` setting

5. **Remove from INSTALLED_APPS**
   - Remove `strawberry_django`

6. **Update frontend**
   - Replace GraphiQL link in `accounts/templates/accounts/profile.html`
   - Replace `modifierGroups` GraphQL call in `trainerlab/templates/trainerlab/partials/_session_form.html` with REST endpoint

7. **Add REST endpoint for modifiers**
   ```python
   # api/v1/endpoints/modifiers.py
   @router.get("/modifier-groups/", response=list[ModifierGroupOut])
   def list_modifier_groups(request, groups: list[str] = Query(None)):
       return get_modifier_groups(groups)
   ```

8. **Tests**
   - Verify GraphQL endpoint returns 404
   - Modifier endpoint works correctly

### Files Changed
- `pyproject.toml` (remove dependencies)
- `SimWorks/config/urls.py` (remove route)
- `SimWorks/config/settings.py` (remove from INSTALLED_APPS)
- `SimWorks/config/schema.py` (delete)
- `SimWorks/config/middleware.py` (remove GraphQL middleware)
- `SimWorks/accounts/schema.py` (delete)
- `SimWorks/simulation/schema.py` (delete)
- `SimWorks/chatlab/schema.py` (delete)
- `SimWorks/trainerlab/schema.py` (delete)
- Templates (update frontend)
- `SimWorks/api/v1/endpoints/modifiers.py` (new)
- `tests/api/test_modifiers.py` (new)

---

## Phase 7: OpenAPI Export & CI (PR #7)

**Goal**: Set up OpenAPI schema export and CI validation.

### Tasks

1. **Create export management command**
   ```python
   # core/management/commands/export_openapi.py
   class Command(BaseCommand):
       def handle(self, *args, **options):
           from api.v1.api import api
           schema = api.get_openapi_schema()
           self.stdout.write(json.dumps(schema, indent=2))
   ```

2. **Add OpenAPI schema to repo** (optional, for versioning)
   - `docs/openapi/v1.json`

3. **CI workflow for schema validation**
   ```yaml
   # .github/workflows/api.yml
   - name: Validate OpenAPI schema
     run: |
       uv run python manage.py export_openapi > /tmp/schema.json
       # Compare with committed schema or validate structure
   ```

4. **API documentation page** (optional)
   - Django Ninja provides `/api/v1/docs` by default
   - Ensure it's accessible in dev, optionally disabled in prod

### Files Changed
- `SimWorks/core/management/commands/export_openapi.py` (new)
- `docs/openapi/v1.json` (new, optional)
- `.github/workflows/api.yml` (new or update)

---

## Phase 8: Rate Limiting (PR #8)

**Goal**: Add per-user and per-IP rate limiting for API endpoints.

### Tasks

1. **Add rate limiting library**
   ```bash
   uv add django-ratelimit
   ```
   Or implement simple Redis-based limiting.

2. **Create rate limit decorator/middleware**
   ```python
   # core/ratelimit.py
   from functools import wraps

   def rate_limit(key: str, limit: int, period: int):
       """Decorator for rate limiting API endpoints."""
       def decorator(func):
           @wraps(func)
           def wrapper(request, *args, **kwargs):
               # Check Redis counter
               # Return 429 if exceeded
               return func(request, *args, **kwargs)
           return wrapper
       return decorator
   ```

3. **Apply to sensitive endpoints**
   - Auth endpoints: 5 req/min per IP
   - Message creation: 30 req/min per user
   - General API: 100 req/min per user

4. **Tests**
   - Rate limit triggers 429 response
   - Limits reset after period
   - Per-user vs per-IP distinction

### Files Changed
- `pyproject.toml` (add library if needed)
- `SimWorks/core/ratelimit.py` (new)
- `SimWorks/api/v1/endpoints/*.py` (apply decorators)
- `tests/api/test_ratelimit.py` (new)

---

## Phase 9: Logging & Telemetry Integration (PR #9)

**Goal**: Integrate correlation ID with structured logging and OpenTelemetry.

### Tasks

1. **Configure structlog**
   ```bash
   uv add structlog
   ```

2. **Create logging configuration**
   ```python
   # config/logging.py
   import structlog

   structlog.configure(
       processors=[
           structlog.contextvars.merge_contextvars,
           structlog.processors.add_log_level,
           structlog.processors.TimeStamper(fmt="iso"),
           structlog.processors.JSONRenderer(),
       ],
   )
   ```

3. **Bind correlation ID in middleware**
   ```python
   # In CorrelationIDMiddleware
   structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
   ```

4. **OpenTelemetry integration** (if using Logfire)
   ```python
   # Set span attribute
   from opentelemetry import trace
   span = trace.get_current_span()
   span.set_attribute("correlation_id", correlation_id)
   ```

5. **Log important operations**
   - Service call start/end
   - Outbox event creation/delivery
   - API request/response (summary)
   - WS connection/disconnect

### Files Changed
- `pyproject.toml` (add structlog)
- `SimWorks/config/logging.py` (new)
- `SimWorks/config/settings.py` (logging config)
- `SimWorks/core/middleware.py` (bind contextvars)
- Various files (add logging calls)

---

## Phase 10: HTMX Message Flow (PR #10)

**Goal**: Ensure HTMX POST message creation works with new architecture.

### Tasks

1. **Verify existing HTMX flow**
   - POST `/chatlab/simulation/{id}/message/` creates message
   - Returns HTML fragment for optimistic update
   - AI response comes via WebSocket

2. **Add message_id to response**
   - Include `message_id` in HTMX response for deduplication

3. **Client-side deduplication**
   - Track `message_id` in Alpine state
   - Skip rendering if already present

4. **Tests**
   - HTMX message creation flow
   - Deduplication with WebSocket events
   - Error handling

### Files Changed
- `SimWorks/chatlab/views.py` (verify/update)
- `SimWorks/chatlab/templates/chatlab/partials/_message.html` (add data-id)
- `SimWorks/chatlab/static/chatlab/js/chat.js` (deduplication)
- `tests/chatlab/test_message_flow.py` (new)

---

## Test Coverage Requirements

Each PR must include tests covering:

| Area | Tests Required |
|------|----------------|
| Correlation ID | Middleware generation, propagation to response, context binding |
| JWT Auth | Token generation, validation, refresh, expiry |
| API Endpoints | CRUD, pagination, authorization, error responses |
| Outbox | Event creation, idempotency, drain worker, concurrent safety |
| WS Envelope | Format validation, all required fields, client deduplication |
| Rate Limiting | 429 on exceed, reset after period |
| OpenAPI | Schema generation, CI validation |
| HTMX Flow | Message creation, deduplication |

---

## Migration Notes

### Backwards Compatibility

During transition:
1. Keep existing WS event handlers working alongside new envelope format
2. GraphQL can be removed in single PR since no tests depend on it
3. Frontend GraphQL calls must be migrated before removal

### Database Migrations

- Phase 4: `OutboxEvent` model
- No other schema changes required

### Rollback Plan

Each phase is a separate PR that can be reverted independently:
1. Foundation: Revert middleware and API mount
2. JWT: Revert auth endpoints, remove from API
3. Core Endpoints: Revert endpoint files
4. Outbox: Revert model and tasks, restore direct `group_send`
5. WS Envelope: Revert consumer changes
6. GraphQL Removal: Restore schema files and dependencies
7. OpenAPI: Revert CI and command
8. Rate Limiting: Remove decorators
9. Logging: Revert to previous logging config
10. HTMX: Revert view changes

---

## Timeline Estimate

| Phase | Dependencies | Complexity |
|-------|--------------|------------|
| 1. Foundation | None | Low |
| 2. JWT Auth | Phase 1 | Medium |
| 3. Core Endpoints | Phases 1, 2 | Medium |
| 4. Outbox | Phase 1 | Medium |
| 5. WS Envelope | Phase 4 | Medium |
| 6. GraphQL Removal | Phases 3, 5 | Low |
| 7. OpenAPI CI | Phase 3 | Low |
| 8. Rate Limiting | Phase 1 | Low |
| 9. Logging | Phase 1 | Low |
| 10. HTMX Flow | Phase 5 | Low |

**Recommended order**: 1 → 2 → 3 → 4 → 5 → 6 → 7 (parallel: 8, 9, 10)

Phases 8, 9, and 10 can be done in parallel after Phase 5 is complete.