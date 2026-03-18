# MedSim docs index

MedSim is a medical simulation and training platform with AI-assisted workflows. This index is the primary entry point for contributors and coding agents.

## Platform docs

- [Architecture at a glance](architecture.md)
- [Quick start](quick-start.md)
- [Deployment tags and release flow](DEPLOYMENT_TAGS.md)
- [WebSocket event contract](WEBSOCKET_EVENTS.md)
- [TrainerLab roadmap and improvements](TRAINERLAB_IMPROVEMENTS.md)

## AI layer docs

- [`orchestrai` package README](../packages/orchestrai/README.md)
- [`orchestrai` deep docs](../packages/orchestrai/docs/full_documentation.md)
- [`orchestrai_django` package README](../packages/orchestrai_django/README.md)
- [`orchestrai_django` docs index](../packages/orchestrai_django/docs/index.md)

## Testing and quality docs

- [Testing lanes](testing/lanes.md)
- [Coverage policy](testing/coverage_policy.md)
- [Testing ownership](testing/ownership.md)

## Boundaries summary

- **MedSim**: product/application platform and user-facing workflows.
- **`orchestrai`**: provider-agnostic orchestration engine/library.
- **`orchestrai_django`**: Django-native integration facade for consuming `orchestrai` in Django apps.

When in doubt: application code should prefer `orchestrai_django` integration points over direct imports from low-level `orchestrai` internals.
