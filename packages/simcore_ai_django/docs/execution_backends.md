# Execution Backends — simcore_ai_django

> Control how AI Services are executed in Django: immediate, deferred, or background (Celery).

---

## Overview

`simcore_ai_django` introduces an **execution layer** that determines *when* and *how* an AI service runs.

Each `DjangoExecutableLLMService` can run:
- **immediately** (inline, synchronous)
- **asynchronously** (via Celery or a future Django task runner)
- **scheduled** (with delay or priority)

---

## Execution Concepts

| Field | Type | Default | Description |
|-------|------|----------|--------------|
| `execution_mode` | `"sync"` / `"async"` | `"sync"` | Whether to run immediately or defer |
| `execution_backend` | `"immediate"` / `"celery"` / `"django_tasks"` | `"immediate"` | Which backend executes the service |
| `execution_priority` | `int` | `0` | Priority from -100 (low) to 100 (high) |
| `execution_run_after` | `float | None` | `None` | Delay in seconds before execution |
| `require_enqueue` | `bool` | `False` | Force async even if mode is `"sync"` |

These may be:
1. Declared as **class attributes**
2. Set **per call** using `.using(...)` or `.enqueue(...)`
3. Controlled globally via **Django settings**

---

## Example

```python
from simcore_ai_django.api.decorators import llm_service
from simcore_ai_django.api.types import DjangoExecutableLLMService

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

Enqueue to Celery with delay:

```python
await GenerateInitialResponse.using(run_after=60).enqueue(simulation=my_sim)
```

---

## Default Resolution Logic

If not explicitly set, each parameter resolves in order:

| Step | Source |
|------|---------|
| 1️⃣ | Attribute on the Service class |
| 2️⃣ | Django setting `AI_EXECUTION_*` |
| 3️⃣ | Hardcoded fallback (`sync` / `immediate` / priority=0) |

### Relevant Django Settings

| Setting | Default | Description |
|----------|----------|--------------|
| `AI_EXECUTION_DEFAULT_MODE` | `"sync"` | Default mode |
| `AI_EXECUTION_DEFAULT_BACKEND` | `"immediate"` | Default backend |
| `AI_EXECUTION_BACKENDS` | `{}` | Registry of backend implementations |
| `AI_EXECUTION_QUEUE` | `"default"` | Default Celery/Django task queue |

---

## Backends

### 1️⃣ Immediate Backend

Runs directly in the current process.

✅ Fastest  
🚫 Blocks current thread  
🔧 Best for lightweight or test scenarios

### 2️⃣ Celery Backend

Runs via Celery worker as an async job.

✅ Scalable  
✅ Non-blocking  
🚫 Requires Celery + broker

```python
await GenerateInitialResponse.using(backend="celery", priority=10).enqueue(...)
```

### 3️⃣ Django Tasks (Future)

Planned for Django-native async background tasks.

---

## ServiceExecutionMixin

`DjangoExecutableLLMService` inherits from `ServiceExecutionMixin` to add helper methods:

```python
GenerateInitialResponse.using(priority=50, run_after=5).enqueue(simulation=my_sim)
GenerateInitialResponse.using(mode="sync").execute(simulation=my_sim)
```

Under the hood:
- `.execute()` dispatches directly
- `.enqueue()` serializes the call to the configured backend

---

## Debugging Execution

Set environment variable:

```
SIMCORE_AI_DEBUG_EXECUTION=true
```

Logs service dispatch trace:

```
[AIService] backend=celery mode=async delay=60 priority=10 → queued
```

---

## Extending Backends

Custom backends can be registered dynamically:

```python
from simcore_ai_django.execution.registry import register_backend

@register_backend("rq")
def enqueue_rq(service_cls, **kwargs):
    # integrate with django-rq
    ...
```

Then used as:

```python
await MyService.using(backend="rq").enqueue(simulation=my_sim)
```

---

## Summary

✅ Declarative async control for AI Services  
✅ Integrated with Django + Celery  
✅ Tracing-friendly for observability  
✅ Easily extensible for custom task runners  

---

© 2025 Jackfruit SimWorks • simcore_ai_django
