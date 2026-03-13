# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SimWorks is a Django-based medical training platform that delivers chat-driven clinical simulations. It uses the **OrchestrAI framework** (a custom-built, provider-agnostic AI orchestration layer) to manage AI services, prompts, response processors, and response schemas across the application.

This is a **uv-managed monorepo workspace** with three main components:
- Main Django project at `/SimWorks`
- `orchestrai` package at `/packages/orchestrai` (core AI orchestration framework)
- `orchestrai_django` package at `/packages/orchestrai_django` (Django integration layer)

## API + Client Architecture

### Non-Negotiable Architecture Decisions

**API Style:**
- **REST-ish JSON API** at `/api/v1/` with **OpenAPI** as the contract (generated from code via Django Ninja)
- **No GraphQL** — Strawberry GraphQL is being removed from the codebase
- Web UI uses **HTMX** for HTML fragments and form submissions, **Alpine.js** for lightweight client behavior
- Mobile clients (future iOS/Android) consume the JSON API with OpenAPI-generated clients

**Route Separation:**
- HTML endpoints: `/chatlab/...`, `/accounts/...`, `/simulation/...` (HTMX + server-rendered templates)
- JSON API endpoints: `/api/v1/...` (pure JSON, no HTML)

**WebSockets:**
- **One WS connection per simulation** at `/ws/simulation/{simulation_id}/`
- WS messages are **hints only**, not source of truth
- Clients must implement **catch-up** via API endpoints after reconnect or missed events
- Notifications WebSocket at `/ws/notifications/` for user-level events

**Authentication:**
- Web: Session cookies (existing Django auth)
- Mobile: JWT tokens with refresh token flow
- WebSocket: Token passed in query param (logs sanitized) or subprotocol header

## Common Commands

### Development Server
```bash
# Run Django development server
uv run python SimWorks/manage.py runserver

# Run migrations
uv run python SimWorks/manage.py migrate

# Create migrations
uv run python SimWorks/manage.py makemigrations

# Create superuser
uv run python SimWorks/manage.py createsuperuser

# Django shell
uv run python SimWorks/manage.py shell
```

### Testing
```bash
# Run all tests with coverage
uv run pytest

# Run specific test file
uv run pytest tests/path/to/test_file.py

# Run tests for specific app
uv run pytest tests/test_simulation.py

# Run with verbose output
uv run pytest -v

# Run without coverage
uv run pytest --no-cov
```

### Docker Development
```bash
# Start dev stack with core services
make dev-up-core

# Start dev stack with core + workers (Celery)
make dev-up-full

# Start detached
make dev-up-full-d

# View logs
make dev-logs

# Shell into container
make dev-shell

# Stop services
make dev-down

# Rebuild and restart
make dev-rerun-full
```

### Production Docker
```bash
# Build production image
make prod-build

# Start production stack
make prod-up

# View logs
make prod-logs

# Stop
make prod-down
```

### Dependency Management
```bash
# Install all dependencies (run from project root)
uv sync

# Add dependency to main project
uv add package-name

# Add dependency to orchestrai package
uv add --package orchestrai package-name

# Add dependency to orchestrai_django package
uv add --package orchestrai-django package-name

# Update dependencies
uv lock --upgrade
```

## Architecture

### OrchestrAI Framework Integration

SimWorks uses a custom AI orchestration framework that provides:
- Provider-agnostic AI service abstraction
- Component-based prompt composition
- Automatic discovery and registration of AI components
- Background task execution via Celery
- Comprehensive audit trails for AI requests/responses

**Key concepts:**

1. **Identity System (Tuple⁴)**: Every component has a 4-tuple identity `(domain, namespace, group, name)`
   - `domain`: Component type (services, response processors, prompts, schemas)
   - `namespace`: Django app or logical grouping (e.g., "simcore", "chatlab")
   - `group`: Sub-grouping within namespace (e.g., "feedback", "patient")
   - `name`: Component class name

2. **Component Discovery**: OrchestrAI automatically discovers components from `{app}/orca/` directories:
   ```
   app_name/
     orca/
       services/       # @service decorated classes
       response processors/         # @response processor decorated classes
       prompts/
         sections/     # @prompt_section decorated classes
       schemas/        # @schema decorated classes
       mixins/         # Identity mixins
       types/          # DTOs and type definitions
   ```

3. **Lifecycle**: The framework initializes during Django startup via `orchestrai_django.apps.OrchestrAIDjangoConfig.ready()`:
   ```python
   # Defined in SimWorks/config/orca.py
   app = OrchestrAI()
   configure_from_django_settings(app)  # Load from Django ORCA_CONFIG
   app.start()  # discover() + finalize()
   ```

### Django Apps Structure

**accounts**: Custom user model, invitations, role/resource authorization

**core**: Shared utilities, middleware, formatters, and API access control
- `core.models.PersistModel`: Base model with common fields
- `core.middleware.HealthCheckMiddleware`: Health check endpoint
- `core.utils.formatters`: JSON/CSV formatters for AI responses

**simulation**: Domain models for simulations, patient data, clinical results
- Central `Simulation` model that anchors sessions, metadata, and artifacts
- Patient demographics, history, lab/radiology results
- Media and feedback management
- `history_registry.py`: Multi-source history aggregation

**chatlab**: Chat sessions, messages, and message media
- Registers history provider for simulation chat messages
- Links messages to simulations

**trainerlab**: Trainer/instructor features and management

**AI Components** (in `{app}/orca/` subdirectories):
- Each app can define services, response processors, prompt sections, and schemas
- Components use mixins to declare their namespace/group for identity derivation

### Creating AI Services

Use the decorator pattern with identity mixins:

```python
# app/orca/mixins/identity.py
from orchestrai_django.identity.mixins import DjangoIdentityMixin

class SimcoreMixin(DjangoIdentityMixin):
    namespace = "simcore"

class FeedbackMixin(DjangoIdentityMixin):
    group = "feedback"

# app/orca/services/feedback.py
from orchestrai_django.decorators import service
from orchestrai_django.services import DjangoBaseService

@service
class GenerateInitialFeedback(FeedbackMixin, DjangoBaseService):
    """Generate the initial patient feedback."""

    async def execute(self, simulation_id: int, **kwargs) -> dict:
        # Service implementation
        # Identity auto-derived: (services, simcore, feedback, GenerateInitialFeedback)
        pass
```

**Service execution modes:**

1. **Immediate (synchronous)**:
   ```python
   service = MyService()
   result = await service.execute(**payload)
   ```

2. **Background (fire-and-forget via Celery)**:
   ```python
   service = MyService()
   call = await service.enqueue(**payload)  # Returns ServiceCall with task_id
   ```

### Creating Prompt Sections

Prompt sections compose together to build complete prompts, rendered in weighted order:

```python
from orchestrai_django.decorators import prompt_section
from orchestrai.prompts import PromptSection
from dataclasses import dataclass

@prompt_section
@dataclass
class PatientNameSection(SimcoreMixin, PromptSection):
    weight = 100  # Higher = earlier in prompt

    async def render_instruction(self, **ctx) -> str | None:
        simulation = ctx.get("simulation")
        return f"You are {simulation.sim_patient_full_name}"
```

### Creating Schemas

**Schemas** define the expected structure of LLM responses. They use Pydantic models decorated with `@schema` for automatic validation and provider compatibility checking.

**Key Features** (OrchestrAI v0.4.0+):
- **Decorator-based validation**: Schemas are validated at decoration time (fail-fast on import)
- **Provider compatibility tagging**: Automatic OpenAI Responses API validation
- **Schema caching**: JSON schema generated once and cached for performance
- **Type safety**: Full Pydantic v2 validation with `extra="forbid"` (strict mode)

**Basic Example**:
```python
from pydantic import Field
from orchestrai_django.components.schemas import DjangoBaseOutputSchema
from orchestrai_django.decorators import schema
from orchestrai_django.types import DjangoOutputItem

@schema
class PatientInitialOutputSchema(
    ChatlabMixin,
    StandardizedPatientMixin,
    DjangoBaseOutputSchema
):
    """Initial patient response schema."""

    messages: list[DjangoOutputItem] = Field(
        ...,
        min_length=1,
        description="Response messages from the simulated patient"
    )
    metadata: list[DjangoOutputItem] = Field(
        ...,
        description="Patient demographics and initial metadata"
    )
```

**What the @schema decorator does**:
1. Validates schema against OpenAI Responses API constraints:
   - Root must be `type: "object"`
   - Must have `properties` field
   - No root-level unions (`anyOf`, `oneOf`)
2. Tags schema with provider compatibility metadata:
   - `_provider_compatibility = {"openai": True}`
   - `_validated_schema` (cached JSON schema)
   - `_validated_at = "decoration"`
3. Fails immediately on import if schema is incompatible (fail-fast)

**Schema Mixins** (for DRY principles):
```python
# chatlab/orca/schemas/mixins.py
from pydantic import Field, BaseModel
from orchestrai_django.types import DjangoOutputItem
from apps.simulation.orca.schemas.output_items import LLMConditionsCheckItem

class PatientResponseBaseMixin(BaseModel):
    """Common fields for patient response schemas."""

    messages: list[DjangoOutputItem] = Field(
        ...,
        min_length=1,
        description="Response messages from the simulated patient"
    )
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        default_factory=list,
        description="Internal workflow conditions (not persisted)"
    )
```

**Identity derivation**:
- Schemas use mixins to declare namespace/group
- Full identity: `schemas.{namespace}.{group}.{ClassName}`
- Example: `schemas.chatlab.standardized_patient.PatientInitialOutputSchema`

**OpenAI Constraints Checklist**:
- ✓ Root is `type: "object"` (not array, string, or union)
- ✓ Has `properties` field
- ✓ No `anyOf`, `oneOf`, `allOf` at root level
- ✓ All fields are JSON-serializable
- ✓ No circular references

**Documentation Pattern**:
```python
@schema
class MySchema(DjangoBaseOutputSchema):
    """
    Brief description.

    **Usage**: When this schema is used

    **Schema Structure**:
    - `field1`: type - Description
    - `field2`: type - Description

    **OpenAI Compatibility**: ✓ Validated at decoration time

    **Persistence**: Handled by `MyPersistence` handler
    - field1 → domain.Model
    - field2 → NOT PERSISTED

    **Identity**: schemas.namespace.group.MySchema
    """
```

### Creating Response processors

Response processors validate and persist AI responses:

```python
from orchestrai_django.decorators import response processor

@response processor
class HotwashInitialCodec(SimcoreMixin, FeedbackMixin):
    """Validates and persists feedback response."""

    async def persist(self, data: dict, **context) -> Any:
        # Validate against schema
        # Save to database
        # Emit signals
        pass
```

### Broadcasting AI Responses via WebSocket

**All AI response schemas** can broadcast events to WebSocket clients using the `post_persist()` hook. This enables real-time UI updates when AI responses are persisted.

**Pattern**: Schema `post_persist()` Hook + Outbox Pattern

```python
# simcore/orca/schemas/feedback.py
from apps.common.outbox.helpers import broadcast_domain_objects

class GenerateInitialSimulationFeedback(BaseModel):
    __persist__ = {"metadata": persist_initial_feedback_block}
    __persist_primary__ = "metadata"

    async def post_persist(self, results, context):
        """Broadcast feedback creation to WebSocket clients."""
        await broadcast_domain_objects(
            event_type="feedback.created",
            objects=results.get("metadata", []),
            context=context,
            payload_builder=lambda fb: {
                "feedback_id": fb.id,
                "key": fb.key,
                "value": fb.value,
            },
        )
```

**Why This Pattern?**:
- ✅ **Locality of Behavior**: Broadcast logic lives with persistence logic
- ✅ **Context-rich**: Access to correlation_id, simulation_id, persisted objects
- ✅ **DRY**: Shared `broadcast_domain_objects()` helper
- ✅ **Testable**: Test persistence + broadcast together
- ✅ **Reliable**: Outbox pattern ensures at-least-once delivery

**Event Types**:
- `chat.message_created` - New patient/AI messages
- `metadata.created` - Labs, radiology, demographics, assessments
- `feedback.created` - Simulation feedback (hotwash)

**Documentation**: See `docs/WEBSOCKET_EVENTS.md` for complete event reference

### Creating Persistence Handlers

**Persistence handlers** are Django-specific components that persist structured LLM outputs (validated schemas) to domain models. They operate out-of-band via a drain worker for reliability and scalability.

**Two-Phase Persistence**:
1. **Phase 1** (service execution): Response JSON saved atomically to `ServiceCallRecord.result`
2. **Phase 2** (drain worker): Persistence handler creates domain objects (Message, Metadata, etc.)

**Identity Conventions**:
- **Domain**: `persist`
- **Namespace**: Django app name (e.g., `chatlab`)
- **Group**: Semantic grouping (e.g., `standardized_patient`)
- **Name**: Handler class name

**Example**:
```python
from orchestrai_django.decorators import persistence_handler
from orchestrai_django.components.persistence import BasePersistenceHandler
from orchestrai.types import Response
from apps.chatlab.orca.mixins import ChatlabMixin
from apps.chatlab.orca.schemas import PatientInitialOutputSchema
from apps.chatlab.models import Message
from apps.simulation.orca.mixins import StandardizedPatientMixin

@persistence_handler
class PatientInitialPersistence(ChatlabMixin, StandardizedPatientMixin, BasePersistenceHandler):
    """
    Persist PatientInitialOutputSchema to Message + Metadata.

    Identity: persist.chatlab.standardized_patient.PatientInitialPersistence
    Handles: (chatlab, schemas.chatlab.standardized_patient.PatientInitialOutputSchema)
    """

    schema = PatientInitialOutputSchema

    async def persist(self, response: Response) -> Message:
        # Idempotency check - ensures exactly-once persistence
        chunk, created = await self.ensure_idempotent(response)

        if not created and chunk.domain_object:
            # Already persisted - return existing
            return chunk.domain_object

        # First persistence - create domain objects
        simulation_id = response.context["simulation_id"]
        data = self.schema.model_validate(response.structured_data)

        # Create Message
        message = await Message.objects.acreate(
            simulation_id=simulation_id,
            content=data.messages[0].content[0].text,
            role="assistant",
            is_from_ai=True,
        )

        # Link to idempotency tracker
        from django.contrib.contenttypes.models import ContentType
        chunk.content_type = await ContentType.objects.aget_for_model(Message)
        chunk.object_id = message.id
        await chunk.asave()

        return message
```

**Discovery**: Handlers discovered from `{app}/orca/persist/*.py` automatically

**Resolution Order**:
1. Try app-specific handler: `(response.namespace, schema_identity)`
2. Fallback to core: `("core", schema_identity)`
3. Skip if no handler found (debug-log only, not an error)

**Idempotency**: Tracked via `PersistedChunk` model
- Unique key: `(call_id, schema_identity)`
- Safe for retries (get_or_create pattern)
- Links to domain object via GenericForeignKey

**Drain Worker**: `process_pending_persistence` task
- Runs periodically (e.g., every 10-30 seconds)
- Claims work with `select_for_update(skip_locked=True)` for concurrency safety
- Processes batch of 100 records
- Retries on failure (max 10 attempts by default)

**Configuration** (Django settings):
```python
ORCHESTRAI = {
    'DOMAIN_PERSIST_MAX_ATTEMPTS': 10,      # Max retry attempts
    'DOMAIN_PERSIST_BATCH_SIZE': 100,        # Records per drain cycle
}
```

**Signals**:
- `domain_object_created`: Emitted after successful persistence
  - Use for side effects like media attachment, WebSocket broadcasts

### Background Tasks with Celery

**Configuration**: Redis broker on queue 1, result backend on queue 2

**Service Call Records**: When services are enqueued, they create `ServiceCallRecord` instances:
- Stores service identity, input payload, status, result
- Links to Celery task via `task_id`
- Provides audit trail for async executions

**Task execution**: `orchestrai_django.tasks.run_service_call(call_id)`
- Fetches ServiceCallRecord from database
- Resolves service class from registry
- Executes and updates record with result/error

### Audit Trail

Two audit models track AI activity:

**AIRequestAudit**: Outbound LLM requests
- Stores messages, tools, response schema, model
- Linked by correlation_id and simulation_pk

**AIResponseAudit**: Inbound LLM responses
- Links back to AIRequestAudit
- Stores tokens used, finish reason, raw response

Signals emitted:
- `ai_request_sent`: After request audit created
- `ai_response_received`: After response audit created
- `ai_response_ready`: After response processor persists
- `ai_response_failed`: On error

## Key Configuration

### Django Settings
Located at `SimWorks/config/settings.py`

**OrchestrAI Configuration**:
```python
ORCA_CONFIG = {
    "MODE": "single",
    "CLIENT": {
        "provider": "openai",
        "surface": "responses",
        "api_key_envvar": "ORCA_PROVIDER_API_KEY",
        "model": "gpt-4o-mini",
    },
}

ORCA_AUTOSTART = True
ORCA_ENTRYPOINT = "config.orca:get_orca"
```

**Environment Variables**:
- `ORCA_PROVIDER_API_KEY`: OpenAI API key (falls back to `OPENAI_API_KEY`)
- `DJANGO_SECRET_KEY`: Django secret key
- `DJANGO_DEBUG`: "true" or "false"
- `DJANGO_ALLOWED_HOSTS`: Comma-separated host list
- `CELERY_BROKER_URL`: Redis connection for Celery broker
- `CELERY_RESULT_BACKEND`: Redis connection for results

### Test Configuration
Located at `pytest.ini`:
```ini
DJANGO_SETTINGS_MODULE = tests.settings_test
```

Coverage targets:
- Main SimWorks code
- orchestrai package
- orchestrai_django package
- Minimum 80% coverage required

## Important Patterns

### Identity Mixins
Always use mixins to define namespace/group for components:
```python
class SimcoreMixin(DjangoIdentityMixin):
    namespace = "simcore"

class FeedbackMixin(DjangoIdentityMixin):
    group = "feedback"
```

### Registry Access
```python
from orchestrai import get_current_app
from orchestrai.registry.services import ensure_service_registry
from orchestrai.identity import Identity

app = get_current_app()
registry = ensure_service_registry(app)
service_cls = registry.get(Identity.get("simcore.feedback.GenerateInitialFeedback"))
```

### History Providers
Apps can register history providers for simulation context:
```python
from apps.simulation.history_registry import register_history_provider

def chatlab_history(simulation_id: int) -> list:
    return Message.objects.filter(simulation_id=simulation_id).order_by('created_at')

register_history_provider("chatlab", chatlab_history)
```

### Response Ordering
AI responses are strictly ordered per simulation with unique sequence constraints. Always respect ordering when seeding or replaying events.

## Working with Tests

Tests are organized in `/tests` directory:
- `tests/test_*.py`: Main Django app tests
- `packages/orchestrai/tests/`: Tests for orchestrai package
- `packages/orchestrai_django/tests/`: Tests for orchestrai_django package

Use `pytest.mark.django_db` for tests requiring database access:
```python
import pytest

@pytest.mark.django_db
def test_simulation_creation():
    simulation = Simulation.objects.create(...)
    assert simulation.id is not None
```

For async tests:
```python
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_async_service():
    service = MyService()
    result = await service.execute(...)
    assert result is not None
```

## Common Gotchas

1. **OrchestrAI app context**: In Celery workers, the OrchestrAI app must be started via `ensure_autostarted()` before accessing registries
2. **Identity collisions**: If two components have the same identity, registration will fail. Use unique combinations of namespace/group/name
3. **Async/sync boundary**: Django ORM is sync-only. Use `sync_to_async` when accessing models from async services
4. **Migration dependencies**: Watch for ordering constraints on AI response models when creating migrations
5. **Redis connectivity**: Both Django cache and Celery require Redis. Verify connectivity for background tasks
6. **Service Call Records**: Background service calls persist their state. Clean up old records periodically to avoid database bloat

## API Contracts

### REST API (`/api/v1/`)

**Framework**: Django Ninja with Pydantic schemas
- OpenAPI schema auto-generated from code
- Export static OpenAPI JSON via `python manage.py export_openapi > openapi.json`
- CI validates OpenAPI schema stability

**Versioning**: URL path versioning (`/api/v1/`, future `/api/v2/`)

**Authentication**:
- Web clients: Session cookies (use existing `@login_required` or Ninja auth)
- Mobile clients: JWT Bearer tokens in `Authorization` header
- Endpoint: `POST /api/v1/auth/token/` returns `{access_token, refresh_token}`
- Refresh: `POST /api/v1/auth/token/refresh/`

**Error Format** (RFC 7807-inspired):
```json
{
  "type": "validation_error",
  "title": "Invalid input",
  "status": 422,
  "detail": "Field 'content' is required",
  "instance": "/api/v1/messages/",
  "correlation_id": "abc123"
}
```

### WebSocket Event Envelope (v1)

All WebSocket events must use this envelope format:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2026-01-19T12:34:56.789Z",
  "simulation_id": "123",
  "type": "message.created",
  "correlation_id": "abc123-or-null",
  "payload": {
    "message_id": "456",
    "content": "..."
  }
}
```

**Required Fields**:
- `event_id` (UUID): Unique event identifier for deduplication
- `created_at` (ISO 8601): Event timestamp
- `simulation_id` (string): Simulation context
- `type` (string): Event type (e.g., `message.created`, `typing.started`, `simulation.ended`)
- `correlation_id` (string|null): Request correlation ID if available
- `payload` (object): Event-specific data

**Event Types**:
- `message.created`: New message — payload includes `message_id`
- `typing.started` / `typing.stopped`: Typing indicators
- `simulation.ended`: Simulation completed
- `metadata.created`: Patient results ready (labs, radiology)
- `feedback.created`: AI feedback generated

**Client Deduplication**:
- Track seen `event_id` values to handle duplicate delivery
- Track seen `message_id` values to prevent duplicate rendering

**WS events are hints**: Clients must fetch full data via API endpoints for catch-up after reconnect.

### TrainerLab SSE (v1)

- Endpoint: `GET /api/v1/trainerlab/simulations/{id}/events/stream/`
- Transport envelope and cursor semantics match the shared outbox SSE stream.
- While idle, TrainerLab emits SSE comment heartbeats in the exact wire form `: keep-alive` at least every 10 seconds.
- SSE responses must remain unbuffered through nginx and any upstream proxy/CDN path so heartbeats are not batched.

### Correlation ID (`X-Correlation-ID`)

**Purpose**: Trace requests across services, logs, and async tasks

**Propagation Rules**:
1. **HTTP requests**: Middleware reads `X-Correlation-ID` header, generates UUID if missing
2. **Attach to context**: Available via `request.correlation_id` (set by middleware)
3. **Logs**: All structured logs include `correlation_id` field
4. **Tasks**: Pass `correlation_id` in service call context
5. **WS events**: Include in event envelope
6. **OpenTelemetry**: Set as span attribute for Logfire visibility

**Middleware** (add to `MIDDLEWARE`):
```python
class CorrelationIDMiddleware:
    def __call__(self, request):
        correlation_id = request.headers.get('X-Correlation-ID') or str(uuid.uuid4())
        request.correlation_id = correlation_id
        response = self.get_response(request)
        response['X-Correlation-ID'] = correlation_id
        return response
```

**Logging Integration**:
```python
import structlog
logger = structlog.get_logger()
logger.info("message_created", correlation_id=request.correlation_id, message_id=msg.id)
```

### Outbox Pattern

**Purpose**: Durable, replayable delivery of side-effects (WebSocket broadcasts, webhooks, etc.)

**Architecture**:
1. **Domain persistence**: OrchestrAI service persists result + creates `OutboxEvent` row atomically
2. **Drain worker**: Separate task reads outbox, delivers to WS/webhooks, marks delivered
3. **Idempotency**: Each event has deterministic `idempotency_key` (e.g., `{call_id}:{event_type}`)
4. **Retry**: Failed deliveries retry with exponential backoff

**OutboxEvent Model**:
```python
class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    idempotency_key = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=100)  # e.g., "ws.message.created"
    payload = models.JSONField()
    simulation_id = models.CharField(max_length=100, db_index=True)
    correlation_id = models.CharField(max_length=100, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, db_index=True)
    delivery_attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(null=True)
```

**Drainer** (hybrid mode):
1. **Periodic task**: Celery Beat runs every 10-30s, processes pending events
2. **Immediate poke**: After persistence, `sync_to_async` triggers drain for low latency
3. **Concurrent safety**: `select_for_update(skip_locked=True)` prevents races

**Delivery Sinks**:
- WebSocket: `channel_layer.group_send()`
- Future: Webhooks, push notifications

### Catch-up API Endpoints

Clients use these to recover missed events after reconnect:

**Messages**:
```
GET /api/v1/simulations/{id}/messages/?after={event_id}&limit=50
```

**Events**:
```
GET /api/v1/simulations/{id}/events/?after={event_id}&limit=50
```

**Cursor Format**: UUID-based `event_id` — opaque cursor, no ordering guarantees beyond "after this ID"

**Response**:
```json
{
  "items": [...],
  "next_cursor": "uuid-or-null",
  "has_more": true
}
```
