# AGENT INSTRUCTIONS — OrchestrAI package

## Scope
These instructions cover the OrchestrAI library under `packages/orchestrai/` (including `src/orchestrai/` and docs).

## Development workflow
- Run the package test suite with `uv run pytest packages/orchestrai` from the repo root.
- Keep the public API stable; add exports through `__init__.py` when introducing new components.
- Avoid introducing import-time side effects—lifecycle steps should remain explicit.

## Coding guidance
- Prefer clear lifecycle naming (`configure()`, `setup()`, `discover()`, `finalize()`, `start()`).
- Keep registries predictable: validate keys early and surface helpful errors for collisions.
- Document new behaviors in `packages/orchestrai/docs/` when adding or changing workflow steps.

## Documentation
- Update `packages/orchestrai/README.md` if usage or installation changes.
- Note meaningful library changes in commit messages so downstream projects can track updates.
