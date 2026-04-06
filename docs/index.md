# MedSim docs index

MedSim is a medical simulation and training platform with AI-assisted workflows.

## Human-focused docs

- [Architecture at a glance](architecture.md)
- [Accounts, billing, and entitlements foundation](architecture/accounts-billing-entitlements.md)
- [Quick start](quick-start.md)
- [Deployment tags and release flow](DEPLOYMENT_TAGS.md)
- [WebSocket event contract](WEBSOCKET_EVENTS.md)
- [TrainerLab iOS backend contract note](trainerlab-ios-backend-contract.md)
- [TrainerLab roadmap and improvements](TRAINERLAB_IMPROVEMENTS.md)

## Package docs

- [`orchestrai` package README](../packages/orchestrai/README.md)
- [`orchestrai` deep docs](../packages/orchestrai/docs/full_documentation.md)
- [`orchestrai_django` package README](../packages/orchestrai_django/README.md)
- [`orchestrai_django` docs index](../packages/orchestrai_django/docs/index.md)

## Testing and quality docs

- [Testing lanes](testing/lanes.md)
- [Coverage policy](testing/coverage_policy.md)
- [Testing ownership](testing/ownership.md)

## Documentation system docs

- [Documentation map (humans + agents)](meta/documentation_map.md)
- [Documentation audit summary](meta/documentation_audit.md)

## Boundaries summary

- **MedSim**: product/application platform and user-facing workflows.
- **`orchestrai`**: provider-agnostic orchestration engine/library.
- **`orchestrai_django`**: Django-native integration facade for consuming `orchestrai` in Django apps.
