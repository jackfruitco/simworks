# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SimWorks is a Django-based medical training platform that delivers chat-driven clinical simulations. It uses the **OrchestrAI framework** (a custom-built, provider-agnostic AI orchestration layer) to manage AI services, prompts, codecs, and response schemas across the application.

This is a **uv-managed monorepo workspace** with three main components:
- Main Django project at `/SimWorks`
- `orchestrai` package at `/packages/orchestrai` (core AI orchestration framework)
- `orchestrai_django` package at `/packages/orchestrai_django` (Django integration layer)

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
   - `domain`: Component type (services, codecs, prompts, schemas)
   - `namespace`: Django app or logical grouping (e.g., "simcore", "chatlab")
   - `group`: Sub-grouping within namespace (e.g., "feedback", "patient")
   - `name`: Component class name

2. **Component Discovery**: OrchestrAI automatically discovers components from `{app}/orca/` directories:
   ```
   app_name/
     orca/
       services/       # @service decorated classes
       codecs/         # @codec decorated classes
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
- Each app can define services, codecs, prompt sections, and schemas
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
class GenerateHotwashInitialResponse(FeedbackMixin, DjangoBaseService):
    """Generate the initial patient feedback."""

    async def execute(self, simulation_id: int, **kwargs) -> dict:
        # Service implementation
        # Identity auto-derived: (services, simcore, feedback, GenerateHotwashInitialResponse)
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

### Creating Codecs

Codecs validate and persist AI responses:

```python
from orchestrai_django.decorators import codec

@codec
class HotwashInitialCodec(SimcoreMixin, FeedbackMixin):
    """Validates and persists feedback response."""

    async def persist(self, data: dict, **context) -> Any:
        # Validate against schema
        # Save to database
        # Emit signals
        pass
```

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
from chatlab.orca.mixins import ChatlabMixin
from chatlab.orca.schemas import PatientInitialOutputSchema
from chatlab.models import Message
from simulation.orca.mixins import StandardizedPatientMixin

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
- `ai_response_ready`: After codec persists
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
service_cls = registry.get(Identity.get("simcore.feedback.GenerateHotwashInitialResponse"))
```

### History Providers
Apps can register history providers for simulation context:
```python
from simulation.history_registry import register_history_provider

def chatlab_history(simulation_id: int) -> list:
    return Message.objects.filter(simulation_id=simulation_id).order_by('created_at')

register_history_provider("chatlab", chatlab_history)
```

### Response Ordering
AI responses are strictly ordered per simulation with unique sequence constraints. Always respect ordering when seeding or replaying events.

## Working with Tests

Tests are organized in `/tests` directory:
- `tests/test_*.py`: Main Django app tests
- `tests/orchestrai/`: Tests for orchestrai package
- `tests/orchestrai_django/`: Tests for orchestrai_django package

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
