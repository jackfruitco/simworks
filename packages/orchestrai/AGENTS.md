# AGENT INSTRUCTIONS — orchestrai scope

## Scope

Applies to `packages/orchestrai/` and subdirectories.

## Local constraints

- Keep `orchestrai` framework-agnostic.
- Do **not** import from `orchestrai_django` in core package code.
- Keep lifecycle explicit and avoid import-time side effects.
- Preserve public API stability; expose new public components intentionally.

## Validation

Run:
```bash
uv run pytest packages/orchestrai
```

## Documentation

Update package docs when behavior/lifecycle/public APIs change:
- `packages/orchestrai/README.md`
- `packages/orchestrai/docs/`
