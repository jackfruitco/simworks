# Services in simcore_ai_django

> How to define, register, and execute AI-backed Django services.

---

## Overview

A **Service** in `simcore_ai_django` is an executable unit that orchestrates:

```
Prompt → Request → Codec → Response
```

Each service:
- Uses a shared **tuple3 identity** (`origin.bucket.name`)
- Can be executed synchronously or asynchronously
- Automatically resolves its PromptSection, Codec, and Schema by matching identity

---

## Base Classes

| Class | Description |
|:--|:--|
| `BaseLLMService` | Core provider-agnostic logic (in `simcore_ai`) |
| `DjangoBaseLLMService` | Adds Django-specific defaults (signals, renderers, codecs) |
| `DjangoExecutableLLMService` | Adds `.execute()` and `.enqueue()` builder helpers |

---

## Decorator

```python
from simcore_ai_django.api.decorators import llm_service
```

The `@llm_service` decorator wraps your class and ensures that:
- It has a valid identity (derived or declared)
- It’s properly registered and ready to execute

---

## Minimal Example

```python
from simcore_ai_django.api.decorators import llm_service
from simcore_ai_django.api.types import DjangoExecutableLLMService

@llm_service
class GenerateInitialResponse(DjangoExecutableLLMService):
    pass
```

✅ This will automatically derive:
```
origin = "chatlab"  # app label
bucket = "default"
name   = "generate_initial_response"
```

and link to matching `PromptSection`, `Codec`, and `Schema` with the same identity.

---

## Identity Mixins

It’s best practice to mix in your app’s `origin` and `bucket`:

```python
from simcore_ai_django.identity.mixins import DjangoIdentityMixin

class ChatlabMixin(DjangoIdentityMixin):
    origin = "chatlab"

class StandardizedPatientMixin(DjangoIdentityMixin):
    bucket = "standardized_patient"
```

Then apply them:

```python
@llm_service
class GenerateInitialResponse(DjangoExecutableLLMService, ChatlabMixin, StandardizedPatientMixin):
    pass
```

Resulting identity:
```
chatlab.standardized_patient.initial
```

---

## Execution

All executable services can be called with `.execute()`:

```python
await GenerateInitialResponse.execute(simulation=my_sim)
```

By default:
- Runs synchronously (immediate)
- Emits tracing spans
- Sends events via Django signal emitter
- Uses autoderived identity for prompt, codec, schema

You can also use `.using()` for overrides:

```python
GenerateInitialResponse.using(backend="celery", run_after=30).enqueue(simulation=my_sim)
```

---

## Common Hooks

| Method | Purpose |
|:--|:--|
| `on_success(self, simulation, resp)` | Called after successful LLM response |
| `on_failure(self, simulation, err)` | Called on error |
| `select_codec(self)` | Override custom codec selection |
| `get_prompt_plan(self, simulation)` | Override prompt composition |
| `build_request_messages(self, simulation)` | Custom message assembly |

---

## Example (Full)

```python
from simcore_ai_django.api.decorators import llm_service
from simcore_ai_django.api.types import DjangoExecutableLLMService
from chatlab.ai.mixins import ChatlabMixin, StandardizedPatientMixin

@llm_service
class GenerateInitialResponse(DjangoExecutableLLMService, ChatlabMixin, StandardizedPatientMixin):
    async def on_success(self, simulation, resp):
        print(f"✅ Response: {resp}")
```

This is all you need — `prompt_section`, `codec`, and `schema` will resolve by identity.

---

## Default Identity Resolution

If not explicitly set:
| Field | Resolution |
|:--|:--|
| `origin` | Django app label |
| `bucket` | `"default"` |
| `name` | Derived from class name (after token stripping) |

---

## Debugging Identity

```python
print(GenerateInitialResponse.identity_tuple())
# ('chatlab', 'standardized_patient', 'initial')
print(GenerateInitialResponse.identity_str())
# 'chatlab.standardized_patient.initial'
```

---

## Service Lifecycle

```text
┌─────────────────────────────┐
│ GenerateInitialResponse     │
│ (Service)                   │
└──────────────┬──────────────┘
               │
               ▼
   PromptSection.build_prompt()
               │
               ▼
       Provider.send_request()
               │
               ▼
      Codec.parse_and_persist()
               │
               ▼
     Schema.validate_response()
```

---

## Advanced Example

```python
@llm_service
class GenerateDifferentialDiagnosis(DjangoExecutableLLMService, ChatlabMixin):
    bucket = "triage"

    async def get_prompt_plan(self, simulation):
        return ["chatlab.triage.initial"]

    async def on_success(self, simulation, resp):
        print(resp.metadata)
```

---

## Summary

✅ **Minimum required**
- Define a subclass of `DjangoExecutableLLMService`
- Decorate with `@llm_service`
- Use identity mixins (recommended)
- Implement nothing if default flow suffices

✅ **Optional**
- Add prompt plan, codec overrides, or lifecycle hooks

✅ **Execution**
```python
await MyService.execute(simulation=my_sim)
```

---

© 2025 Jackfruit SimWorks • simcore_ai_django
