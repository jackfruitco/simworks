# MedSim

[![ci](https://github.com/jackfruitco/simworks/actions/workflows/ci.yml/badge.svg)](https://github.com/jackfruitco/simworks/actions/workflows/ci.yml)
[![security](https://github.com/jackfruitco/simworks/actions/workflows/security.yml/badge.svg)](https://github.com/jackfruitco/simworks/actions/workflows/security.yml)
[![coverage](https://codecov.io/gh/jackfruitco/simworks/graph/badge.svg)](https://codecov.io/gh/jackfruitco/simworks)

MedSim (formerly SimWorks) is a medical simulation and training platform built on Django, HTMX, and AI-driven orchestration workflows.

> **Naming note:** MedSim is the product name. The repository and some internal paths still use legacy `simworks` identifiers.

## Architecture at a glance

MedSim is organized into three layers:

1. **Product/application layer (`SimWorks/`)**
   Django apps for simulation workflows, including clinician/student-facing experiences such as ChatLab and trainer-facing flows such as TrainerLab.
2. **Core orchestration library (`packages/orchestrai`)**
   Framework-agnostic orchestration primitives for providers, services, schemas, tools/codecs, and registries.
3. **Django integration layer (`packages/orchestrai_django`)**
   Django-first facade/adapters for using `orchestrai` in app code, including settings integration, persistence hooks, and service execution helpers.

## Documentation map (start here)

- **Platform docs:** [`docs/index.md`](docs/index.md)
- **Architecture overview:** [`docs/architecture.md`](docs/architecture.md)
- **Local development quick start:** [`docs/quick-start.md`](docs/quick-start.md)
- **Testing lanes and ownership:** [`docs/testing/`](docs/testing)
- **`orchestrai` package docs:** [`packages/orchestrai/README.md`](packages/orchestrai/README.md)
- **`orchestrai_django` package docs:** [`packages/orchestrai_django/README.md`](packages/orchestrai_django/README.md)

## Local development and validation

```bash
# Install workspace dependencies
uv sync

# Run Django dev server
uv run python SimWorks/manage.py runserver

# Run complete test suite
uv run pytest
```

### Reproduce CI lanes locally

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

## Build and release

- `ci` runs on every pull request and on pushes to `main`.
- `security` runs for pull requests targeting `main` and on a weekly schedule.
- `cd-staging` runs on every push to `main`, builds the runtime image once, publishes `sha-<gitsha>` and `staging`, and triggers staging Portainer redeploy when configured.
- `cd-release` runs when a GitHub Release is published (and optional manual dispatch by `release_tag`), verifies and promotes an existing immutable image digest to `vX.Y.Z` and `stable`, and optionally triggers production Portainer redeploy.

See deployment tag conventions and workflow details in [`docs/DEPLOYMENT_TAGS.md`](docs/DEPLOYMENT_TAGS.md).
