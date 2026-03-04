# Test Lanes

## Lane Overview

- `lint_and_checks`: pre-commit, `manage.py check`, and OpenAPI schema checks.
- `unit_fast`: isolated tests selected by `unit` marker.
- `integration_core`: DB/request-cycle tests selected by `integration` marker.
- `package_contracts`: package-level tests selected by `contract` marker.
- `coverage_gate`: package-scoped coverage generation and floor enforcement.

## Local Commands

- Root unit lane:
  - `uv run pytest -m "unit and not slow" -n auto --dist loadscope --durations=25`
- Root integration lane:
  - `uv run pytest -m "integration and not slow" -n auto --dist loadscope --durations=25`
- OrchestrAI package tests:
  - `uv run pytest packages/orchestrai/tests -m "not slow"`
- OrchestrAI Django package tests:
  - `uv run pytest packages/orchestrai_django/tests -m "not slow" --ds=orchestrai_django.tests.settings`
- SimWorks composition integration tests:
  - `uv run pytest tests -m "integration and not slow"`

## Marker Taxonomy

- `unit`: fast isolated tests with no DB/network requirements.
- `component`: boundary-level tests with fakes/stubs.
- `integration`: Django/ORM/request-cycle and cross-module integration tests.
- `contract`: public API/schema compatibility tests for packages.
- `system`: high-level system smoke tests.
- `e2e`: end-to-end tests across full stack boundaries.
- `slow`: tests excluded from fast PR loops.

## Defaults

Pytest defaults are configured in `pyproject.toml` with:

- `-ra --maxfail=1 --strict-markers`
- explicit marker registration
- package and app test path discovery
