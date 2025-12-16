# OrchestrAI Documentation

`orchestrai` is a minimal orchestration layer for structured AI workflows. The core focuses on explicit lifecycle control, predictable registries, and import safety.

## Architecture overview

- **OrchestrAI app** – owns configuration, loader, registries, and lifecycle hooks.
- **Registries** – lightweight, frozen after `finalize()`, storing services, codecs, providers, clients, and prompt sections.
- **Shared decorators** – allow registering components before an app exists; callbacks run during `finalize()` for every app.
- **Loader** – optional autodiscovery helper that imports modules declared in `DISCOVERY_PATHS`.

## Public API

```python
from orchestrai import OrchestrAI, current_app, get_current_app
```

- `OrchestrAI` – main application class
- `current_app` – context-local proxy to the active app
- `get_current_app()` – returns the active app or creates a default one

## Lifecycle

1. **configure(mapping=None, namespace=None)** – apply settings from a mapping.
2. **config_from_object(obj, namespace=None)** – load settings from a dotted object path.
3. **config_from_envvar(envvar="ORCHESTRAI_CONFIG_MODULE", namespace=None)** – load settings from an environment variable.
4. **setup()** – instantiate the loader and populate registries for `CLIENTS` and `PROVIDERS`.
5. **discover()** – call the loader’s `autodiscover(app, modules)` for each path in `DISCOVERY_PATHS`.
6. **finalize()** – run shared decorator callbacks and freeze registries.
7. **start()/run()** – print the jumping-orca banner, run discovery, finalize, and emit a component summary; idempotent.

Each method is idempotent and avoids network calls; nothing heavy happens during import.

## Configuration keys

- `CLIENT` – name of the default client to expose via `app.client`.
- `CLIENTS` – mapping of client definitions.
- `PROVIDERS` – mapping of provider definitions.
- `DISCOVERY_PATHS` – iterable of dotted module paths to import during discovery. The defaults
  import OrchestrAI’s contrib provider backends/codecs and include glob patterns for common
  project layouts (`*.orca.services`, `*.orca.output_schemas`, `*.orca.codecs`, `*.ai.services`).
  Patterns resolve to real modules before import; unmatched patterns are skipped safely.
- `LOADER` – dotted path to a loader class; defaults to the lightweight base loader.
- `MODE` – optional runtime mode flag.

Unknown keys are stored but unused by the core, letting extensions consume their own configuration without conflicts.

## Registries

Registries are simple, thread-safe mappings with three phases:

1. **register(name, obj)** – allowed before freeze.
2. **get(name)** – retrieve a registered object.
3. **freeze()** – prevent further mutation; invoked automatically during `finalize()`.

The app exposes `services`, `codecs`, `providers`, `clients`, and `prompt_sections` registries. Use `app.clients.register(...)` or decorators to populate them.

## Shared decorators and finalize callbacks

Decorators in `orchestrai.shared` let you register components before an app exists:

```python
from orchestrai.shared import shared_service

@shared_service()
def ping():
    return "pong"

app = OrchestrAI().finalize()
assert "ping" in app.services
```

Callbacks are consumed during every app’s `finalize()`, so multiple app instances see the shared registrations.

## Current app management

Use `app.as_current()` to scope the active application:

```python
with app.as_current():
    # proxies such as current_app resolve to `app`
    client = app.client
```

Nested contexts restore the previous app automatically.

## Discovery and loaders

The default loader performs no implicit work until `discover()` is called. By default it imports
OrchestrAI contrib registration modules plus any modules matching the built-in glob patterns.
Provide your own `DISCOVERY_PATHS` tuple to extend or override that list, or set it to an empty
tuple to disable all automatic discovery.

```python
app.configure({"DISCOVERY_PATHS": ["myapp.services", "myapp.codecs"]})
app.discover()
```

The defaults already scan `orchestrai.contrib.provider_backends` and
`orchestrai.contrib.provider_codecs`, and attempt to import modules matching `*.orca.services`,
`*.orca.output_schemas`, `*.orca.codecs`, and `*.ai.services` when they exist on `sys.path`.

If you need custom behavior, point `LOADER` to your own loader class implementing `autodiscover(app, modules)`.

## Tracing

The core ships with lightweight span helpers in `orchestrai.tracing.tracing` that collect attributes without external dependencies. Integrations can wrap these spans to feed real tracing backends.

## Error handling and idempotency

- Repeated calls to `setup()`, `discover()`, `finalize()`, and `start()` are safe and return the app unchanged.
- Registries raise `RuntimeError` if mutated after freeze.
- Loader failures surface the original import error to aid debugging.

## Deprecations

- Legacy tracing backends were removed in favor of the lightweight span helpers.

## Example end-to-end

```python
from orchestrai import OrchestrAI
from orchestrai.shared import shared_service

@shared_service()
def hello(name: str = "world"):
    return f"hello {name}"

app = OrchestrAI()
app.configure({"CLIENT": "local", "CLIENTS": {"local": {"name": "local"}}})
app.start()

with app.as_current():
    print("Services:", app.services.all())
```
