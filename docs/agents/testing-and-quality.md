# Testing and quality workflow

## Baseline checks

Run the smallest relevant checks for your change scope, then broaden as needed.

```bash
# formatting / patch sanity
git diff --check

# full test suite
uv run pytest
```

## Package-scoped checks

```bash
uv run pytest packages/orchestrai
uv run pytest packages/orchestrai_django
```

## Django app checks

```bash
uv run python SimWorks/manage.py check
```

## Documentation checks

- Verify updated markdown links resolve.
- Search for stale path references after doc restructuring.
- Ensure `AGENTS.md` / `CLAUDE.md` references match current file layout.

## CI lane reproduction

Refer to root `README.md` for lane-specific commands used in CI.
