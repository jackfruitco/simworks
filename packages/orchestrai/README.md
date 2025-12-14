# OrchestrAI
***or-kis-stray-eye***

A lightweight, provider-agnostic orchestration layer for building structured AI workflows in pure Python. The refactored core favors explicit lifecycles, import safety, and predictable registries.

Import the application class directly from the top-level package:

```python
from orchestrai import OrchestrAI

app = OrchestrAI()
```

The legacy `orchestrai.apps` entry point emits a `DeprecationWarning`; prefer the canonical import above.

## Quick start

Create an app, apply configuration, and run the lifecycle explicitly:

```python
from orchestrai import OrchestrAI

app = (
    OrchestrAI()
    .configure(
        {
            "CLIENT": "demo-client",
            "CLIENTS": {"demo-client": {"name": "demo-client", "api_key": "..."}},
            "PROVIDERS": {"demo-provider": {"backend": "openai", "model": "gpt-4o-mini"}},
        }
    )
    .setup()      # prepare loader and registries
    .discover()   # optionally import discovery modules
    .finalize()   # attach shared callbacks and freeze registries
)

with app.as_current():
    # resolve the default client from the registry
    client = app.client
```

`start()` (or `run()`) is a convenience wrapper that performs discovery, finalization, prints the jumping-orca welcome banner once, and summarizes registered components.

## Lifecycle overview

1. **configure** – apply settings from mappings, objects, or environment variables.
2. **setup** – prepare the loader and populate registries for clients, providers, codecs, and services.
3. **discover** – import configured discovery modules via the loader.
4. **finalize** – run shared decorators/finalizers and freeze registries.
5. **start** / **run** – convenience method that prints the banner, runs discovery, and finalizes the app.

The app never performs network or discovery work during import; all actions are explicit.

## Documentation

Comprehensive guides live in the [`docs/`](docs/) directory:

- [Quick Start](docs/quick_start.md) – create an app, configure it, and make your first request.
- [Full Guide](docs/full_documentation.md) – deep dive into configuration, lifecycle hooks, registries, and discovery.

## Contributing

1. Create a virtual environment and install the package in editable mode: `pip install -e .[dev]`.
2. Run the test suite before submitting changes: `pytest`.
3. Follow conventional commit messages and open a pull request with a clear summary of your changes.

## License

MIT License © 2024 OrchestrAI contributors
