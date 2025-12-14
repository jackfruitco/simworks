# simcore_ai_django

`simcore_ai_django` provides the Django integration layer for the `simcore_ai` framework. It wires tuple³ identities (`origin.bucket.name`) into Django apps so AI services, prompt sections, codecs, and response schemas can find each other automatically.

## Key capabilities

- Django-aware identity derivation for services, codecs, prompt sections, and schemas.
- Decorators (`@llm_service`, `@codec`, `@prompt_section`) that register components safely with collision handling.
- Execution helpers (`DjangoExecutableLLMService`) with synchronous and asynchronous dispatch support.
- Registry-backed codec resolution and Django signal emitters for observability.

## Documentation

Detailed docs live in [`docs/`](docs/index.md):

- [Quick start](docs/quick-start.md)
- [Services](docs/services.md)
- [Prompt sections](docs/prompt_sections.md)
- [Codecs](docs/codecs.md)
- [Schemas](docs/schemas.md)
- [Execution backends](docs/execution_backends.md)
- [Signals & emitters](docs/signals.md)

## Development

Install the package in editable mode and run the test suite from the project root:

```bash
uv pip install -e packages/simcore_ai_django
pytest
```

