# MedSim domain and simulation rules

## Product-level constraints

- MedSim is a medical simulation/training platform; documentation and behavior should prioritize clinical simulation correctness and traceability.
- Trainer/instructor controls and learner-facing simulation state must remain clearly separated.

## Realtime/event model

- Use a single simulation-scoped WebSocket stream pattern where specified.
- Treat WS as near-realtime hints; API state remains source of truth.
- Emit durable events via outbox-backed flows for recoverability.

## API contract discipline

- Use generated OpenAPI from code for `/api/v1/`; avoid manual spec drift.
- Keep API error formats and correlation identifiers consistent across endpoints/tasks/events.

## UI architecture constraints

- Keep web UI server-rendered with HTMX + Alpine patterns unless explicitly changed by architecture decisions.
- Avoid introducing SPA frameworks contrary to current direction.
