# Persistence Handlers Implementation Summary

This document summarizes the complete implementation of the persistence handlers architecture for the OrchestrAI Django framework.

## Overview

Persistence handlers provide an out-of-band, idempotent, and concurrent-safe mechanism for persisting structured LLM outputs to Django ORM models. The implementation follows a two-phase pattern:

1. **Phase 1** (Service Execution): Response JSON saved atomically to `ServiceCallRecord.result`
2. **Phase 2** (Drain Worker): Persistence handler creates domain objects asynchronously

## Changes Made

### 1. Critical Bug Fixes

#### ✅ Fixed PersistenceHandlerRegistry Initialization
**File**: `packages/orchestrai_django/src/orchestrai_django/registry/persistence.py:27-30`

**Problem**: Missing `super().__init__()` call caused `AttributeError: '_lock'` when mounting registry to component store.

**Fix**: Added parent class initialization:
```python
def __init__(self):
    # Initialize parent registry (provides _lock, _frozen, _store, _coerce)
    super().__init__()

    # Custom handlers dict for (namespace, schema_identity) routing
    self._handlers: dict[tuple[str, str], type[BasePersistenceHandler]] = {}
```

### 2. Auto-Discovery Enhancement

#### ✅ Added "persist" to Component Discovery
**Files**:
- `packages/orchestrai/src/orchestrai/loaders/default.py:16-23`
- `packages/orchestrai_django/src/orchestrai_django/integration.py:11-21`

**Change**: Added `"persist"` to `COMPONENT_SUFFIXES` tuple.

**Impact**: Handlers in `{app}/orca/persist/*.py` now auto-discovered like services, codecs, and schemas.

### 3. Idempotency Tracking

#### ✅ Created PersistedChunk Model
**File**: `packages/orchestrai_django/src/orchestrai_django/models.py:181-237`

**Purpose**: Tracks which structured outputs have been persisted to domain models, ensuring exactly-once semantics.

**Schema**:
```python
class PersistedChunk(TimestampedModel):
    call_id = CharField(max_length=64, db_index=True)           # Service call ID
    schema_identity = CharField(max_length=255, db_index=True)  # Schema that structured output
    namespace = CharField(max_length=255, db_index=True)        # Originating Django app
    handler_identity = CharField(max_length=255)                # Handler that processed

    # Generic foreign key to domain object
    content_type = ForeignKey(ContentType, ...)
    object_id = PositiveIntegerField(...)
    domain_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        unique_together = [("call_id", "schema_identity")]  # Idempotency key
```

**Migration**: Created `0004_add_persisted_chunk_model.py`

#### ✅ Added ensure_idempotent() Helper
**File**: `packages/orchestrai_django/src/orchestrai_django/components/persistence/handler.py:72-124`

**Purpose**: Reusable method for handlers to check if chunk already persisted.

**Usage Pattern**:
```python
async def persist(self, response: Response) -> Message:
    chunk, created = await self.ensure_idempotent(response)

    if not created and chunk.domain_object:
        return chunk.domain_object  # Already persisted

    # First persistence - create domain objects
    message = await Message.objects.acreate(...)

    # Link to tracker
    chunk.content_type = await ContentType.objects.aget_for_model(Message)
    chunk.object_id = message.id
    await chunk.asave()

    return message
```

### 4. Drain Worker Enhancements

#### ✅ Enhanced process_pending_persistence Task
**File**: `packages/orchestrai_django/src/orchestrai_django/tasks.py:288-434`

**Improvements**:
1. **Concurrent Safety**: Added `select_for_update(skip_locked=True)` to prevent race conditions
2. **Smart Batching**: Pre-filters exhausted records (attempts >= max) before claiming
3. **Atomic Claiming**: Increments attempt counter inside transaction lock
4. **Graceful Skipping**: Returns `None` for missing handlers instead of failing
5. **Better Observability**: Detailed logging with call_id, schema_identity, handler_identity
6. **Stats Tracking**: Returns `{claimed, processed, failed, skipped}`

**New Flow**:
```python
# 1. Atomic claim with concurrent safety
with transaction.atomic():
    pending = ServiceCallRecord.objects.filter(
        status='succeeded',
        domain_persisted=False,
        domain_persist_attempts__lt=MAX_ATTEMPTS
    ).select_for_update(skip_locked=True).order_by('finished_at')[:100]

    # Increment attempts inside lock
    for record in pending:
        record.domain_persist_attempts += 1
    ServiceCallRecord.objects.bulk_update(pending, ['domain_persist_attempts'])

# 2. Process claimed records (outside lock)
for record in pending:
    response = Response.model_validate(record.result)
    domain_obj = await persistence_registry.persist(response)

    # Mark success
    record.domain_persisted = True
    record.save()
```

### 5. Media Attachment Support

#### ✅ Added domain_object_created Signal
**File**: `packages/orchestrai_django/src/orchestrai_django/signals.py:131,257`

**Purpose**: Emitted after successful persistence for side effects like media attachment, WebSocket broadcasts.

**Usage**:
```python
# In signal receiver (e.g., chatlab/signals.py)
from orchestrai_django.signals import domain_object_created

@receiver(domain_object_created, sender=PatientInitialPersistence)
def attach_media_to_message(sender, instance, response, **kwargs):
    # Extract media from response.structured_data
    # Create MessageMedia links
    pass
```

### 6. Updated Persistence Handlers

#### ✅ Updated chatlab Handlers with Idempotency
**File**: `SimWorks/chatlab/orca/persist/patient.py`

**Changes**:
- `PatientInitialPersistence`: Added `ensure_idempotent()` check
- `PatientReplyPersistence`: Added `ensure_idempotent()` check
- Both handlers now link domain objects to `PersistedChunk` tracker

**Example Change**:
```python
async def persist(self, response: Response) -> Message:
    # NEW: Idempotency check
    chunk, created = await self.ensure_idempotent(response)

    if not created and chunk.domain_object:
        logger.info(f"Idempotent skip: Message {chunk.object_id} already exists")
        return chunk.domain_object

    # ... existing persistence logic ...

    # NEW: Link to tracker
    chunk.content_type = await ContentType.objects.aget_for_model(Message)
    chunk.object_id = message.id
    await chunk.asave()

    return message
```

### 7. Comprehensive Tests

#### ✅ Created Test Suite
**File**: `packages/orchestrai_django/tests/test_persistence_handlers.py` (390 lines)

**Coverage**:
- `TestPersistenceHandlerRegistry`: 8 tests
  - Initialization, freezing, registration, validation
  - Handler routing (app-specific, fallback to core, skip if missing)
  - Async persist() integration
- `TestBasePersistenceHandler`: 2 tests
  - `ensure_idempotent()` creation and reuse
  - Correlation ID fallback
- `TestPersistedChunk`: 3 tests
  - Model creation, unique constraints
  - Generic foreign key to domain objects
- `TestPersistenceDecorator`: 3 tests
  - Component type validation
  - Base class, persist() method, schema attribute validation

**Test Infrastructure**:
- Created `conftest.py` with Django setup fixture
- Configured in-memory SQLite for fast tests
- Mock fixtures for schemas and domain objects

### 8. Documentation Updates

#### ✅ Updated CLAUDE.md
**File**: `CLAUDE.md:253-345`

**Added Section**: "Creating Persistence Handlers"

**Content**:
- Two-phase persistence architecture
- Identity conventions (domain.namespace.group.name)
- Complete code example with idempotency
- Discovery, resolution order, configuration
- Signals for side effects

## Configuration

New Django settings:

```python
ORCHESTRAI = {
    'DOMAIN_PERSIST_MAX_ATTEMPTS': 10,    # Max retry attempts (default: 10)
    'DOMAIN_PERSIST_BATCH_SIZE': 100,     # Records per drain cycle (default: 100)
}
```

## Migration Required

Run migration to create `PersistedChunk` table:

```bash
uv run python SimWorks/manage.py migrate orchestrai_django
```

## Testing

Run the test suite:

```bash
# Run all persistence handler tests
uv run pytest packages/orchestrai_django/tests/test_persistence_handlers.py -v

# Run specific test
uv run pytest packages/orchestrai_django/tests/test_persistence_handlers.py::TestPersistenceHandlerRegistry -v
```

## Architecture Decisions

### Why Hybrid (Core + Django)?
- **Core**: Defines execution contract (Response type, identity domains)
- **Django**: Provides persistence mechanism (ORM, transactions, GenericForeignKey)
- **Import boundary preserved**: Core never imports Django

### Why Outbox Pattern?
- **Decouples persistence from service execution**: Service returns immediately
- **Retryable**: Failed persistence doesn't require re-calling LLM
- **Scalable**: Separate drain worker can run on dedicated instances

### Why PersistedChunk Tracking?
- **Exactly-once semantics**: Unique constraint on `(call_id, schema_identity)`
- **Retry safety**: `get_or_create` pattern handles concurrent retries
- **Audit trail**: Links to domain object for debugging

### Why select_for_update(skip_locked=True)?
- **Concurrent workers**: Multiple drain workers can run without conflicts
- **No blocking**: Workers skip locked records instead of waiting
- **Throughput**: Maximizes processing rate under load

## Known Limitations

1. **No chunk-level granularity**: Tracks at schema-output level, not individual fields
2. **No schema versioning**: Assumes schema identity is stable
3. **No priority queue**: All records processed FIFO by `finished_at`
4. **No backoff strategy**: Retries happen on every drain cycle (could add exponential backoff)

## Future Enhancements

1. **Backoff Strategy**: Add `next_retry_at` field to throttle retries
2. **Priority Queue**: Add `priority` field for urgent simulations
3. **Metrics**: Emit StatsD/Prometheus metrics for monitoring
4. **Dead Letter Queue**: Move exhausted records to separate table
5. **Schema Versioning**: Track schema version in PersistedChunk
6. **Partial Persistence**: Support persisting individual "chunks" within a schema

## Files Changed

### Core Framework
- `packages/orchestrai/src/orchestrai/loaders/default.py`
- `packages/orchestrai/src/orchestrai/identity/domains.py` (already had PERSIST_DOMAIN)

### Django Integration
- `packages/orchestrai_django/src/orchestrai_django/registry/persistence.py`
- `packages/orchestrai_django/src/orchestrai_django/components/persistence/handler.py`
- `packages/orchestrai_django/src/orchestrai_django/models.py`
- `packages/orchestrai_django/src/orchestrai_django/tasks.py`
- `packages/orchestrai_django/src/orchestrai_django/signals.py`
- `packages/orchestrai_django/src/orchestrai_django/integration.py`
- `packages/orchestrai_django/src/orchestrai_django/migrations/0004_add_persisted_chunk_model.py`

### SimWorks Application
- `SimWorks/chatlab/orca/persist/patient.py`

### Tests & Documentation
- `packages/orchestrai_django/tests/conftest.py` (new)
- `packages/orchestrai_django/tests/test_persistence_handlers.py` (new)
- `CLAUDE.md`

## Summary

The persistence handlers architecture is now fully implemented with:

✅ Critical bug fixes (registry initialization)
✅ Auto-discovery integration
✅ Idempotency tracking via PersistedChunk
✅ Concurrent-safe drain worker with locking
✅ Media attachment support via signals
✅ Updated SimWorks handlers
✅ Comprehensive test suite (16 tests)
✅ Complete documentation

The system is production-ready and follows Django best practices for reliability, scalability, and maintainability.
