# SimWorks Quick Start

This guide walks you through preparing a local SimWorks development environment, running the Django stack, and exercising the bundled tooling.

## Prerequisites
- Python 3.13 or newer (the project pins `requires-python = ">=3.13"`).【F:pyproject.toml†L1-L6】
- [`uv`](https://github.com/astral-sh/uv) for workspace-aware dependency management and script execution (SimWorks uses `uv` for installing dependencies and running management commands).【F:pyproject.toml†L6-L45】
- Redis and PostgreSQL services, or the ability to fall back to SQLite for development.【F:SimWorks/config/settings.py†L104-L205】

## Project setup
1. **Install dependencies**
   ```bash
   uv sync
   ```
   `uv sync` installs the Django project plus the workspace packages (`simcore-ai`, `simcore-ai-django`) declared in `pyproject.toml`.

2. **Configure environment variables**
   Create a `.env` (or export variables in your shell) covering at least:
   - `DJANGO_SECRET_KEY` and `DJANGO_DEBUG` for Django core settings.【F:SimWorks/config/settings.py†L18-L26】
   - `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` for host filtering during local testing.【F:SimWorks/config/settings.py†L27-L41】
   - Database settings (`DATABASE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`). Choose `postgresql` for the default Postgres configuration or `sqlite3` for a file-backed database.【F:SimWorks/config/settings.py†L104-L128】
   - Redis connection secrets (`REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`) which feed Channels, Celery, and result backends.【F:SimWorks/config/settings.py†L195-L218】
   - AI provider credentials such as `OPENAI_API_KEY`, optional `AI_BASE_URL`, and model overrides (`AI_DEFAULT_MODEL`, `AI_IMAGE_MODEL`). These plug into the unified `SIMCORE_AI` configuration.【F:SimWorks/config/settings.py†L130-L193】
   - Site metadata (`SITE_NAME`, `SITE_ADMIN_NAME`, `SITE_ADMIN_EMAIL`) if you want custom branding in templates or outgoing messages.【F:SimWorks/config/settings.py†L266-L272】

3. **Apply database migrations**
   ```bash
   uv run python SimWorks/manage.py migrate
   ```
   Migrations materialize the simulation, chat, accounts, and AI audit tables required for the platform.【F:PROJECT_OVERVIEW.md†L79-L83】

4. **Create a superuser (optional but recommended)**
   ```bash
   uv run python SimWorks/manage.py createsuperuser
   ```

## Running the stack
1. **Start the Django development server**
   ```bash
   uv run python SimWorks/manage.py runserver 0.0.0.0:8000
   ```
   The server loads the installed apps (`accounts`, `core`, `simcore`, `chatlab`, etc.) and exposes the `/health` check for readiness probes.【F:SimWorks/config/settings.py†L45-L83】【F:SimWorks/core/middleware.py†L4-L14】

2. **Launch background workers**
   Celery powers AI services and scheduled jobs. Run at least one worker after Redis is available:
   ```bash
   uv run celery -A SimWorks.config worker -l info
   ```
   The worker executes `run_service_task`, which loads AI services and forwards work to the orchestration runner.【F:SimWorks/config/settings.py†L195-L218】【F:packages/simcore_ai_django/src/simcore_ai_django/tasks.py†L1-L25】

   To process scheduled beats (optional), start a beat scheduler:
   ```bash
   uv run celery -A SimWorks.config beat -l info
   ```

3. **Test WebSocket support (optional)**
   Channels uses Redis-backed layers. Ensure the Redis credentials you configured allow the development server and workers to connect.【F:SimWorks/config/settings.py†L195-L218】

4. **Verify health and GraphQL access**
   - Visit `http://localhost:8000/health` to see the JSON health response.【F:SimWorks/core/middleware.py†L4-L14】
   - Access the private GraphQL endpoint after authenticating with a staff or `core.read_api` user. Unauthorized requests are rejected by `PrivateGraphQLView`.【F:SimWorks/core/views/views.py†L26-L43】

## Running tests
Execute the pytest suite with `uv` so the proper Django settings module is loaded:
```bash
uv run pytest
```
Pytest is preconfigured to point at `config.settings` and collect tests from the `tests/` directory.【F:pyproject.toml†L47-L50】

## Next steps
- Seed sample simulations using the Django admin or management commands once they are introduced.
- Review `docs/README.md` for deeper architecture details.
- Integrate additional AI providers by extending the `SIMCORE_AI["PROVIDERS"]` section with new credentials or base URLs.【F:SimWorks/config/settings.py†L130-L170】
