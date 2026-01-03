# Execution Backends — orchestrai_django

> Control how AI Services are dispatched in Django: inline, deferred, or background.

---

## Overview

`DjangoExecutableLLMService` combines Django-aware defaults with the core execution mixin. Each service can run:

- **immediately** (inline, synchronous)
- **asynchronously** (e.g., via Celery)
- **scheduled** (delay + priority)

Execution behavior is driven by service attributes, per-call overrides, and the `AI_EXECUTION_BACKENDS` setting.

---

## Execution Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `execution_mode` | `"sync"` / `"async"` | `settings.AI_EXECUTION_BACKENDS["DEFAULT_MODE"]` → `"sync"` | Whether to run immediately or enqueue. |
| `execution_backend` | `"immediate"` / `"celery"` / custom | `settings.AI_EXECUTION_BACKENDS["DEFAULT_BACKEND"]` → `"immediate"` | Backend implementation used for dispatch. |
| `execution_priority` | `int` | `0` | Relative priority (-100 .. 100). |
| `execution_run_after` | `float | None` | `None` | Seconds to delay execution. |
| `require_enqueue` | `bool` | `False` | Force async even if mode is `"sync"`. |

These values can be:
1. Declared as **class attributes** on the service.
2. Set **per call** using `.using(...)` + `.execute()` / `.enqueue()`.
3. Resolved from settings if left unset.

---

## Example

```python
from orchestrai_django.api.decorators import llm_service
from orchestrai_django.api.types import DjangoExecutableLLMService

@llm_service
class GenerateInitialResponse(DjangoExecutableLLMService):
    execution_mode = "async"
    execution_backend = "celery"
    execution_priority = 25
```

Run immediately:

```python
await GenerateInitialResponse.execute(simulation=my_sim)
```

Enqueue with overrides:

```python
await GenerateInitialResponse.using(run_after=60, priority=10).enqueue(simulation=my_sim)
```

---

## Default Resolution Logic

When resolving execution parameters, the service checks in order:

1. Per-call overrides from `.using(...)`.
2. Service class attributes.
3. `AI_EXECUTION_BACKENDS` setting.
4. Hard-coded fallbacks (`mode="sync"`, `backend="immediate"`, `priority=0`).

### `AI_EXECUTION_BACKENDS` Structure

```python
AI_EXECUTION_BACKENDS = {
    "DEFAULT_MODE": "sync",
    "DEFAULT_BACKEND": "immediate",
    "CELERY": {
        "queue_default": "ai-default",
    },
}
```

Custom keys are ignored by the built-in helpers but can be consumed by your backends.

---

## Built-in Backends

### Immediate Backend

- Runs the service inline within the calling process.
- Default backend; no extra configuration required.

### Celery Backend

- Dispatches work to a Celery worker.
- Reads `queue_default` from `AI_EXECUTION_BACKENDS["CELERY"]` if provided.
- Requires `orchestrai_django.execution.celery_backend` to be importable (Celery optional dependency).

Register additional backends with the helper:

```python
from orchestrai_django.execution.registry import register_backend

@register_backend("rq")
def enqueue_rq(service_cls, *, call_ctx):
    ...  # custom implementation
```

Then use via `.using(backend="rq")`.

---

## Debugging Dispatch

- The execution entrypoint emits OpenTelemetry spans (`ai.execute`, `ai.enqueue`) detailing backend, mode, and correlation IDs.
- Inspect the context passed to backends via `orchestrai_django.execution.helpers.span_attrs_from_ctx`.
- Loggers under `orchestrai_django.execution` provide additional diagnostics when set to DEBUG.

---

## Summary

- Execution behavior is configurable per service, per call, or globally via settings.
- Immediate and Celery backends are bundled; others can be registered dynamically.
- Use `.using(...)` to adjust backend, delay, and priority without subclassing.

---

© 2025 Jackfruit SimWorks • orchestrai_django
