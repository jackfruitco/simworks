# WebSocket Event Contract

This document describes the durable outbox-backed event contract used for real-time MedSim simulation updates.

## Source of Truth

The canonical registry lives in `SimWorks/apps/common/outbox/event_types.py`.

- Server emitters must use registry constants.
- Server envelopes emit only canonical event names.
- Browser clients may temporarily accept deprecated aliases during rollout, but aliases are not canonical output.

## Canonical Naming Rules

Canonical outbox event types must follow this exact contract:

- `domain.subject.action`
- exactly 3 segments
- lowercase letters with dot separators only
- no underscores
- domains limited to `simulation`, `patient`, `message`, `feedback`
- actions limited to `created`, `updated`, `removed`, `triggered`, `completed`, `failed`

State transitions belong in payload metadata, not the event name.

Examples:

- `simulation.status.updated` with payload `{ "status": "running", "from": "seeded", "to": "running" }`
- `message.delivery.updated` with payload `{ "status": "delivered" }`
- `feedback.generation.updated` with payload `{ "status": "retrying" }`
- `patient.intervention.updated` with payload `{ "assessment_status": "effective" }`

## Transport Envelope

All durable events use the same envelope shape:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "simulation.status.updated",
  "created_at": "2026-03-21T12:34:56.789Z",
  "correlation_id": "abc-xyz",
  "payload": {
    "status": "running",
    "from": "seeded",
    "to": "running"
  }
}
```

For `*.status.updated` events, payload should include:

- `status`
- `from` when applicable
- `to` when applicable

## Canonical Event Registry

### `message`

- `message.item.created`
- `message.delivery.updated`

### `feedback`

- `feedback.item.created`
- `feedback.generation.updated`
- `feedback.generation.failed`

### `simulation`

- `simulation.status.updated`
- `simulation.brief.created`
- `simulation.brief.updated`
- `simulation.snapshot.updated`
- `simulation.plan.updated`
- `simulation.patch.completed`
- `simulation.tick.triggered`
- `simulation.summary.updated`
- `simulation.runtime.failed`
- `simulation.preset.updated`
- `simulation.command.updated`
- `simulation.adjustment.updated`
- `simulation.note.created`
- `simulation.annotation.created`

### `patient`

- `patient.metadata.created`
- `patient.results.updated`
- `patient.injury.created`
- `patient.injury.updated`
- `patient.illness.created`
- `patient.illness.updated`
- `patient.problem.created`
- `patient.problem.updated`
- `patient.recommendedintervention.created`
- `patient.recommendedintervention.updated`
- `patient.recommendedintervention.removed`
- `patient.intervention.created`
- `patient.intervention.updated`
- `patient.assessmentfinding.created`
- `patient.assessmentfinding.updated`
- `patient.assessmentfinding.removed`
- `patient.diagnosticresult.created`
- `patient.diagnosticresult.updated`
- `patient.resource.updated`
- `patient.disposition.updated`
- `patient.recommendationevaluation.created`
- `patient.vital.created`
- `patient.vital.updated`
- `patient.pulse.created`
- `patient.pulse.updated`

## Representative Payloads

### `message.item.created`

```json
{
  "event_type": "message.item.created",
  "payload": {
    "message_id": 456,
    "content": "I have chest pain.",
    "role": "assistant",
    "display_name": "Patient",
    "status": "completed",
    "media_list": []
  }
}
```

### `message.delivery.updated`

```json
{
  "event_type": "message.delivery.updated",
  "payload": {
    "id": 456,
    "status": "delivered",
    "retryable": false
  }
}
```

### `patient.metadata.created`

```json
{
  "event_type": "patient.metadata.created",
  "payload": {
    "metadata_id": 789,
    "kind": "lab_result",
    "key": "wbc_count",
    "value": "12.5"
  }
}
```

### `feedback.generation.updated`

```json
{
  "event_type": "feedback.generation.updated",
  "payload": {
    "simulation_id": 123,
    "status": "retrying",
    "retry_count": 1
  }
}
```

### `simulation.status.updated`

```json
{
  "event_type": "simulation.status.updated",
  "payload": {
    "status": "paused",
    "from": "running",
    "to": "paused"
  }
}
```

### `patient.intervention.updated`

```json
{
  "event_type": "patient.intervention.updated",
  "payload": {
    "intervention_id": 42,
    "status": "completed",
    "assessment_status": "effective",
    "effectiveness": "effective"
  }
}
```

## Filtering

Prefix filtering works directly against canonical names. Useful filters include:

- `simulation.`
- `patient.`
- `patient.problem.`
- `message.delivery.`

## Realtime Model

MedSim uses a reliable event delivery pattern:

1. Domain persistence creates an outbox row in the same transactional flow.
2. The drain worker delivers outbox rows to the simulation WebSocket group.
3. Clients use the WebSocket as a near-realtime hint channel.
4. Clients recover missed durable events through the catch-up API.

WebSocket delivery is not the source of truth. The API remains authoritative.

## Compatibility

During migration, some browser clients may still accept deprecated aliases such as:

- `chat.message_created`
- `message_status_update`
- `simulation.state_changed`
- `feedback.failed`
- `feedback.retrying`

Those aliases are compatibility inputs only. Canonical server output uses the registry names above.
