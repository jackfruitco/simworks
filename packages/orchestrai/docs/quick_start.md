# Quick Start

This quick start walks through creating an `OrchestrAI` app, configuring a client and provider, and running the lifecycle explicitly.

## 1. Install the package

```bash
pip install orchestrai
```

## 2. Create and configure an app

The app is intentionally light at import time. Apply configuration explicitly, then run the lifecycle.

```python
from orchestrai import OrchestrAI

app = OrchestrAI()
app.configure(
    {
        "CLIENT": "demo-client",
        "CLIENTS": {"demo-client": {"name": "demo-client", "api_key": "token"}},
        "PROVIDERS": {"demo": {"backend": "openai", "model": "gpt-4o-mini"}},
        # DISCOVERY_PATHS defaults to built-in contrib modules plus glob patterns such as
        # "*.orca.services" and "*.ai.services". Override to add custom modules or set to an
        # empty tuple to disable automatic discovery entirely.
        "DISCOVERY_PATHS": ["my_project.services"],
    }
)
```

If your project follows the `orca` or `ai` conventions (for example `my_project/orca/services`),
the defaults will attempt to import those modules automatically. Provide your own
`DISCOVERY_PATHS` list to opt into other modules or set it to an empty tuple `()` to skip
autodiscovery altogether.

## 3. Run the lifecycle

Call the explicit lifecycle steps. `start()` is a shortcut that calls `discover()` and `finalize()`, prints the jumping-orca banner once, and emits a concise listing of registered components.

```python
app.start()
```

Or run each step manually:

```python
app.setup()      # prepares loader and registries
app.discover()   # imports configured discovery modules
app.finalize()   # attaches shared decorators and freezes registries
```

## 4. Use the current app

Use the context manager to scope the current app while resolving registries or clients:

```python
with app.as_current():
    default_client = app.client
    available_services = app.services.all()
```

## 5. Register components with decorators

Shared decorators enqueue work until `finalize()` runs. For example, register a service before the app exists:

```python
from orchestrai.shared import shared_service

@shared_service()
def hello_world():
    return "hello"

app.finalize()
assert "hello_world" in app.services
```

Explore the [Full Guide](full_documentation.md) for details on registries, discovery, and extending the framework.
