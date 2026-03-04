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

## Reproduce CI Test Command Locally

```bash
DJANGO_SETTINGS_MODULE=config.settings uv run pytest -ra \
  --cov=SimWorks \
  --cov=packages/orchestrai/src/orchestrai \
  --cov=packages/orchestrai_django/src/orchestrai_django \
  --cov-report=term-missing \
  --cov-report=xml \
  --cov-fail-under=80
```
