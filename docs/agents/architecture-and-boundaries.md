# Architecture and dependency boundaries

## Layer model

1. **MedSim app layer (`SimWorks/`)** — product workflows, APIs, templates, domain logic.
2. **`orchestrai`** — framework-agnostic orchestration engine.
3. **`orchestrai_django`** — Django integration facade over `orchestrai`.

## Dependency direction

- App code can consume `orchestrai_django` and `orchestrai` public APIs as needed.
- `orchestrai_django` depends on `orchestrai`.
- `orchestrai` must remain framework-agnostic and must not import `orchestrai_django`.

## API and realtime constraints

- REST/OpenAPI is the canonical API contract.
- WebSocket events are hints; clients must recover state via API catch-up.
- Outbox pattern is required for durable side-effects/events.

## Naming and migration discipline

- Use MedSim branding in human-facing product descriptions.
- Preserve technical identifiers and paths when they are part of stable runtime contracts.
