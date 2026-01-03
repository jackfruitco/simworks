# AGENT INSTRUCTIONS — OrchestrAI Django integration

## Scope
Applies to the Django integration package in `packages/orchestrai_django/`, including `src/orchestrai_django/` and docs.

## Development workflow
- Run tests from the repo root with `uv run pytest packages/orchestrai_django`.
- Keep Django wiring explicit: registrations and signal emitters should not fire at import time unless necessary for Django app loading.
- Align examples and docs with the current package name and API surface.
- Maintain one-way dependencies: plug into core `orchestrai` via fixups or adapters; never add imports in the core package back to `orchestrai_django`.

## Coding guidance
- Validate tuple³ identities (`origin.bucket.name`) before registry insertion; raise clear errors on collisions.
- Prefer decorators (`@llm_service`, `@codec`, `@prompt_section`) for registrations and keep them idempotent.
- When adding execution helpers, ensure synchronous and asynchronous paths stay consistent.

## Documentation
- Update `packages/orchestrai_django/docs/` and README quick starts when behavior changes.
- Mention integration-impacting changes in commit messages so downstream projects stay aligned.
