# AGENT INSTRUCTIONS — orchestrai_django scope

## Scope

Applies to `packages/orchestrai_django/` and subdirectories.

## Local constraints

- Keep Django wiring explicit and predictable.
- Maintain one-way dependency on `orchestrai` (no reverse coupling in core package).
- Keep sync/async execution paths behaviorally aligned.
- Keep registration identities validated and idempotent.

## Validation

Run:
```bash
uv run pytest packages/orchestrai_django
```

## Documentation

Update integration docs when behavior/API changes:
- `packages/orchestrai_django/README.md`
- `packages/orchestrai_django/docs/`
