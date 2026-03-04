# Coverage Policy (Phase A)

## Gate Model

Coverage is enforced per package in CI:

- `orchestrai >= 57%`
- `orchestrai_django >= 30%`
- `simworks >= 54%`

Patch coverage is enforced by Codecov status checks with a required target of `>= 90%` for changed lines.

Aggregate coverage remains visible in reports but is not a hard failure gate in Phase A.

## Coverage Reports

CI emits package-scoped XML artifacts to avoid path-collision issues:

- `coverage-orchestrai.xml`
- `coverage-orchestrai-django.xml`
- `coverage-simworks.xml`

## Exclusions

The following paths are excluded from gate-driven remediation and should not be treated as signal regressions:

- Django migrations (`**/migrations/*.py`)
- generated files and build artifacts
- framework boilerplate and non-executable module shims, including:
  - `__init__.py`
  - `config/asgi.py`
  - `config/wsgi.py`
  - settings-only shim modules used for environment bootstrapping

Exclusions should be kept minimal and explicit; adding new exclusions requires a short rationale in PR notes.
