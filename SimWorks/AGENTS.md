# AGENT INSTRUCTIONS — SimWorks Django project

## Scope
These instructions apply to the Django project in `SimWorks/` and any subdirectories unless a deeper `AGENTS.md` overrides them.

## Development workflow
- Use `uv run` for management commands (e.g., `uv run python manage.py migrate`, `uv run python manage.py runserver`).
- Prefer `uv run pytest` for test execution; target specific apps or tests when possible to keep runs fast.
- When changing models, run `uv run python manage.py makemigrations` and include generated migration files.

## Coding guidance
- Keep Django settings changes minimal and environment-agnostic; prefer settings driven by environment variables.
- Favor explicit imports and avoid implicit side effects in module import time (no network calls during import).
- Maintain consistent formatting for templates and static assets; keep template blocks minimal and readable.

## Documentation
- Update relevant docs in `PROJECT_OVERVIEW.md`, `docs/`, or app-level READMEs when behavior or workflows change.
- Include concise notes in commit messages describing the Django-area change.
