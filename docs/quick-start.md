# MedSim quick start

This guide helps you run MedSim locally for development.

> MedSim is the product name. The repository still includes legacy `SimWorks` path names.

## Prerequisites

- Python 3.14+
- [`uv`](https://github.com/astral-sh/uv)
- PostgreSQL and Redis (or SQLite for minimal local runs)

## 1) Install dependencies

```bash
uv sync
```

This installs the Django app plus workspace packages (`orchestrai`, `orchestrai-django`).

## 2) Configure environment

Set at least:
- Django core: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`
- Host config: `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`
- Database: `DATABASE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- Redis: `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
- AI provider keys, for example `OPENAI_API_KEY`

## 3) Run migrations

```bash
uv run python SimWorks/manage.py migrate
```

## 4) Start the app

```bash
uv run python SimWorks/manage.py runserver 0.0.0.0:8000
```

## 5) Run tests

```bash
uv run pytest
```

## Optional: Docker/Make workflow

```bash
make dev-up-core
make dev-logs
make dev-down
```

## Next docs

- Architecture: [`architecture.md`](architecture.md)
- Testing docs: [`testing/`](testing/)
- `orchestrai` docs: [`../packages/orchestrai/README.md`](../packages/orchestrai/README.md)
- `orchestrai_django` docs: [`../packages/orchestrai_django/README.md`](../packages/orchestrai_django/README.md)
