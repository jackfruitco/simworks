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
        "DISCOVERY_PATHS": ["my_project.services"],
    }
)
```

## 3. Run the lifecycle

Call the explicit lifecycle steps. `start()` is a shortcut that calls `discover()` and `finalize()` and prints the welcome banner once.

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
