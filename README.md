# SimWorks

[![ci](https://github.com/jackfruitco/simworks/actions/workflows/ci.yml/badge.svg)](https://github.com/jackfruitco/simworks/actions/workflows/ci.yml)
[![security](https://github.com/jackfruitco/simworks/actions/workflows/security.yml/badge.svg)](https://github.com/jackfruitco/simworks/actions/workflows/security.yml)
[![coverage](https://codecov.io/gh/jackfruitco/simworks/graph/badge.svg)](https://codecov.io/gh/jackfruitco/simworks)

SimWorks is a Django-based simulation platform with integrated AI orchestration workflows.

## Build And Release

- `ci` runs on every pull request and on pushes to `main`.
- `security` runs for pull requests targeting `main` and on a weekly schedule.
- `cd-release` builds and tags release-candidate and staging images.
- `cd-promote` promotes a verified release candidate digest to production tags.

See deployment tag conventions and workflow details in `docs/DEPLOYMENT_TAGS.md`.

## Reproduce CI Lanes Locally

```bash
# unit_fast
uv run pytest -m "unit and not slow" -n auto --dist loadscope --durations=25

# integration_core
uv run pytest -m "integration and not slow" -n auto --dist loadscope --durations=25

# package contracts
uv run pytest packages/orchestrai/tests -m "contract and not slow"
uv run pytest packages/orchestrai_django/tests -m "contract and not slow" --ds=orchestrai_django.tests.settings

# package-scoped coverage gate inputs
uv run pytest packages/orchestrai/tests -m "not slow" --cov=packages/orchestrai/src/orchestrai --cov-report=xml:coverage-orchestrai.xml
uv run pytest packages/orchestrai_django/tests -m "not slow" --ds=orchestrai_django.tests.settings --cov=packages/orchestrai_django/src/orchestrai_django --cov-report=xml:coverage-orchestrai-django.xml
uv run pytest tests -m "not slow" --cov=SimWorks --cov-report=xml:coverage-simworks.xml
```
