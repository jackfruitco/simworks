# WebSocket Event Broadcasting

This document describes the WebSocket event system used for real-time updates in SimWorks.

## Overview

SimWorks uses a **reliable event delivery pattern** combining:
1. **WebSocket hints** for real-time notifications
2. **Outbox pattern** for durable event storage
3. **Catch-up API** for event recovery after reconnection

## Architecture

### Event Flow

```
AI Service → persist_schema() → post_persist() hook
                                      ↓
                             OutboxEvent (database)
                                      ↓
                          Drain Worker (periodic + immediate)
                                      ↓
                     channel_layer.group_send("simulation_{id}")
                                      ↓
                        ChatConsumer.outbox_event()
                                      ↓
                            WebSocket Client
```

### Key Components

**Schema `post_persist()` Hooks**:
- Called after domain persistence completes
- Creates outbox events via `broadcast_domain_objects()` helper
- Has access to correlation_id, simulation_id, and persisted objects

**Outbox Table**:
- Stores events durably before delivery
- Enables at-least-once delivery guarantees
- Supports catch-up API for missed events

**Drain Worker**:
- Periodic task (runs every 10-30s)
- Immediate poke after event creation (low latency)
- Uses `select_for_update(skip_locked=True)` for concurrency safety

**WebSocket Consumer**:
- `ChatConsumer.outbox_event()` receives events from drain worker
- Forwards standardized envelope to connected clients
- No business logic - pure passthrough

## Event Types

### 1. chat.message_created

**Triggered when**: Patient or AI generates a message

**Payload**:
```json
{
  "event_id": "uuid",
  "event_type": "chat.message_created",
  "created_at": "2026-02-22T12:34:56.789Z",
  "simulation_id": "123",
  "correlation_id": "abc-xyz",
  "payload": {
    "message_id": 456,
    "content": "Hello, I have chest pain",
    "role": "assistant",
    "is_from_ai": true,
    "display_name": "Patient",
    "timestamp": "2026-02-22T12:34:56.789Z",
    "image_requested": false
  }
}
```

**Frontend Action**: Append message to chat UI, scroll to bottom

**Source**: `PatientInitialOutputSchema`, `PatientReplyOutputSchema` (post_persist)

---

### 2. metadata.created

**Triggered when**: Labs, radiology, demographics, or assessments are persisted

**Payload**:
```json
{
  "event_id": "uuid",
  "event_type": "metadata.created",
  "created_at": "2026-02-22T12:35:00.123Z",
  "simulation_id": "123",
  "correlation_id": "abc-xyz",
  "payload": {
    "metadata_id": 789,
    "kind": "lab_result",
    "key": "wbc_count",
    "value": "12.5"
  }
}
```

**Frontend Action**: Refresh metadata panels (labs, radiology, demographics)

**Source**: `PatientInitialOutputSchema`, `PatientResultsOutputSchema` (post_persist)

**Metadata Kinds**:
- `lab_result` - Laboratory test results
- `rad_result` - Radiology findings
- `patient_demographics` - Patient demographics
- `patient_history` - Medical history
- `generic` - Generic metadata

---

### 3. feedback.created

**Triggered when**: Simulation feedback (hotwash) is generated

**Payload**:
```json
{
  "event_id": "uuid",
  "event_type": "feedback.created",
  "created_at": "2026-02-22T12:40:00.456Z",
  "simulation_id": "123",
  "correlation_id": "abc-xyz",
  "payload": {
    "feedback_id": 321,
    "key": "hotwash_correct_diagnosis",
    "value": "true"
  }
}
```

**Frontend Action**: Update feedback panel, show completion badge

**Source**: `GenerateInitialSimulationFeedback` (post_persist)

---

### 4. typing.started / typing.stopped

**Triggered when**: User or AI starts/stops typing

**Payload**:
```json
{
  "type": "user_typing",
  "user": "user@example.com",
  "display_initials": "JD"
}
```

**Frontend Action**: Show/hide typing indicator

**Source**: Manual broadcast via `handle_typing()` consumer method

---

### 5. simulation.ended

**Triggered when**: Simulation completes or times out

**Payload**:
```json
{
  "type": "simulation_ended",
  "simulation_id": 123,
  "reason": "completed"
}
```

**Frontend Action**: Show completion modal, disable input

**Source**: Manual broadcast via consumer methods

## Client Implementation Guide

### 1. WebSocket Connection

```javascript
const ws = new WebSocket(`wss://example.com/ws/simulation/${simulationId}/`);

// Track seen events for deduplication
const seenEventIds = new Set();
let lastEventId = null;

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  // Deduplicate by event_id
  if (data.event_id) {
    if (seenEventIds.has(data.event_id)) {
      console.debug('Duplicate event, ignoring:', data.event_id);
      return;
    }
    seenEventIds.add(data.event_id);
    lastEventId = data.event_id;
  }

  // Route by event_type
  handleEvent(data);
};
```

### 2. Event Routing

```javascript
function handleEvent(envelope) {
  switch (envelope.event_type) {
    case 'chat.message_created':
      handleNewMessage(envelope.payload);
      break;

    case 'metadata.created':
      handleNewMetadata(envelope.payload);
      break;

    case 'feedback.created':
      handleNewFeedback(envelope.payload);
      break;

    default:
      console.warn('Unknown event type:', envelope.event_type);
  }
}
```

### 3. Catch-up After Reconnect

```javascript
async function catchUp(simulationId, lastEventId) {
  let cursor = lastEventId;
  let hasMore = true;

  while (hasMore) {
    const response = await fetch(
      `/api/v1/events/${simulationId}/events/?cursor=${cursor}&limit=50`,
      {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      }
    );

    const data = await response.json();

    // Process events
    data.items.forEach(handleEvent);

    // Update cursor
    cursor = data.next_cursor;
    hasMore = data.has_more;
  }
}

// Usage:
ws.onclose = async () => {
  console.log('WebSocket closed, catching up...');
  await catchUp(simulationId, lastEventId);
  // Reconnect WebSocket
};
```

### 4. Deduplication Strategy

**Track by `event_id`**:
- Events have unique UUIDs
- Store in Set or Map for O(1) lookup
- Clear old IDs after successful catch-up

**Track by domain object ID**:
- Messages: Track `message_id` in Set
- Metadata: Track `metadata_id` in Set
- Prevents duplicate rendering even if event_id missed

```javascript
const seenMessageIds = new Set();

function handleNewMessage(payload) {
  if (seenMessageIds.has(payload.message_id)) {
    console.debug('Duplicate message, ignoring:', payload.message_id);
    return;
  }
  seenMessageIds.add(payload.message_id);

  // Render message...
}
```

## Catch-up API

### Endpoint

```
GET /api/v1/events/{simulation_id}/events/
```

### Parameters

- `cursor` (optional): UUID of last seen event
- `limit` (optional): Max events to return (1-100, default 50)

### Response

```json
{
  "items": [
    {
      "event_id": "uuid",
      "event_type": "chat.message_created",
      "created_at": "2026-02-22T12:34:56.789Z",
      "correlation_id": "abc-xyz",
      "payload": { ... }
    }
  ],
  "next_cursor": "uuid-or-null",
  "has_more": true
}
```

### Usage

1. Track `lastEventId` from WebSocket events
2. On reconnect, call API with `cursor=lastEventId`
3. Process returned events in order
4. Continue fetching while `has_more` is true
5. Resume WebSocket listening

## Testing

### Manual Testing

1. **Start development server**: `uv run python SimWorks/manage.py runserver`
2. **Open browser console**: Connect to WebSocket
3. **Trigger AI response**: Send message or generate feedback
4. **Verify events**: Check console for outbox events

### Integration Testing

```python
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_outbox_events_created(context):
    schema = PatientInitialOutputSchema.model_validate({...})
    await persist_schema(schema, context)

    # Verify outbox events created
    from apps.common.models import OutboxEvent
    events = await OutboxEvent.objects.filter(
        simulation_id=context.simulation_id,
        event_type="chat.message_created",
    ).acount()
    assert events > 0
```

## Monitoring

### Key Metrics

- **Outbox event backlog**: `OutboxEvent.objects.filter(delivered_at__isnull=True).count()`
- **Drain worker latency**: Time between `created_at` and `delivered_at`
- **Failed deliveries**: `OutboxEvent.objects.filter(delivery_attempts__gt=3).count()`

### Logging

All outbox events are logged with:
- `event_type`
- `simulation_id`
- `correlation_id`
- Delivery status

Search logs for: `"Outbox event created"`, `"Delivered outbox event"`

## Troubleshooting

### Events not arriving

1. **Check outbox table**: Are events being created?
   ```sql
   SELECT * FROM core_outboxevent WHERE delivered_at IS NULL ORDER BY created_at DESC LIMIT 10;
   ```

2. **Check drain worker**: Is Celery running?
   ```bash
   celery -A config inspect active
   ```

3. **Check WebSocket connection**: Is client connected to correct room?
   ```python
   # In Django shell
   from channels.layers import get_channel_layer
   channel_layer = get_channel_layer()
   ```

### Duplicate events

1. **Client-side**: Ensure event_id deduplication is implemented
2. **Server-side**: Check for duplicate outbox creation (idempotency_key should prevent)

### Missing events after reconnect

1. **Verify catch-up API**: Test `/api/v1/events/{simulation_id}/events/`
2. **Check cursor tracking**: Ensure lastEventId is persisted
3. **Verify event retention**: Old events may be archived/deleted

## Best Practices

### For Frontend Developers

✅ **Always implement event_id deduplication**
✅ **Implement catch-up flow on reconnect**
✅ **Handle unknown event types gracefully**
✅ **Track message_id/metadata_id for domain-level deduplication**
✅ **Log correlation_id for debugging**

❌ **Don't assume WebSocket delivery is reliable**
❌ **Don't use WebSocket as source of truth**
❌ **Don't block UI on WebSocket events**

### For Backend Developers

✅ **Use `broadcast_domain_objects()` helper in post_persist()**
✅ **Include correlation_id in all events**
✅ **Document new event types in this file**
✅ **Test outbox event creation in persistence tests**

❌ **Don't broadcast directly to WebSocket**
❌ **Don't skip outbox pattern**
❌ **Don't add business logic to consumers**

## Adding New Event Types

1. **Implement `post_persist()` in schema**:
   ```python
   async def post_persist(self, results, context):
       from apps.common.outbox.helpers import broadcast_domain_objects

       await broadcast_domain_objects(
           event_type="your.new_event",
           objects=results.get("field", []),
           context=context,
           payload_builder=lambda obj: {"id": obj.id, ...},
       )
   ```

2. **Add tests** in `tests/*/test_persist_schema.py`

3. **Document event type** in this file

4. **Update frontend** to handle new event type

5. **Update OpenAPI docs** in `api/v1/schemas/events.py`

## References

- CLAUDE.md - Overall architecture and patterns
- core/outbox/ - Outbox pattern implementation
- api/v1/endpoints/events.py - Catch-up API endpoint
- chatlab/consumers.py - WebSocket consumer implementation
