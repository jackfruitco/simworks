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

Identity derivation is **Django-aware** and **collision-safe**, automatically using your app label, mixins, and token stripping rules (duplicate names are suffixed like `-2`, `-3`).

---

## Base Classes

| Class | Description |
|:--|:--|
| `BaseService` | Core provider-agnostic logic (in `simcore_ai`) |
| `DjangoBaseService` | Adds Django-specific defaults (signals, renderers, codecs) |
| `DjangoExecutableLLMService` | Adds `.execute()` and `.enqueue()` builder helpers |

---

## Decorator

```python
from simcore_ai_django.api.decorators import llm_service
```

The `@llm_service` decorator wraps your **async function** (or class) into a service and ensures that:
- It has a valid identity (derived or declared)
- It’s properly registered and ready to execute

Supports both `@llm_service` and `@llm_service(origin="...", bucket="...", name="...")`.

---

## Minimal Example

```python
from simcore_ai_django.api.decorators import llm_service

@llm_service  # or: @llm_service(namespace="chatlab", kind="standardized_patient", name="initial")
async def generate_initial(simulation, slim):
    print("✅ AI service executed successfully")
    return {"ok": True}
```

```
origin = "chatlab"  # app label
bucket = "standardized_patient"  # or "default" if not set elsewhere
name   = "initial"
```

and link to matching `PromptSection`, `Codec`, and `Schema` with the same identity.

---

## Identity Mixins

**Note:** For function-based services, prefer passing `origin`/`bucket` via the decorator when you need overrides. Mixins remain useful if you choose a class-based service style.

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

```python
await generate_initial.execute(simulation=my_sim)
```

By default:
- Runs synchronously (immediate)
- Emits tracing spans
- Sends events via Django signal emitter
- Uses autoderived identity for prompt, codec, schema

You can also use `.using()` for overrides:

```python
generate_initial.using(backend="celery", run_after=30).enqueue(simulation=my_sim)
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
from chatlab.ai.mixins import ChatlabMixin, StandardizedPatientMixin  # optional if using class-based style

@llm_service(origin="chatlab", bucket="standardized_patient", name="initial")
async def generate_initial(simulation, slim):
    print("✅ Response emitted")
    return {"ok": True}
```

This is all you need — `prompt_section`, `codec`, and `schema` will resolve by identity.

---

## Default Identity Resolution

If not explicitly set:
| Field | Resolution |
|:--|:--|
| `origin` | Django app label |
| `bucket` | `"default"` |
| `name` | Derived from function/class name after token stripping |

---

## Debugging Identity

```python
print(generate_initial.identity_tuple())
# ('chatlab', 'standardized_patient', 'initial')
print(generate_initial.identity_str())
# 'chatlab.standardized_patient.initial'
```

---

## Service Lifecycle

```text
┌─────────────────────────────┐
│ generate_initial()          │
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
from simcore_ai_django.api.decorators import llm_service

@llm_service(origin="chatlab", bucket="triage", name="differential_diagnosis")
async def generate_differential(simulation):
    # Optionally specify a prompt plan on the service class:
    generate_differential.prompt_plan = (("chatlab", "triage", "initial"),)
    # Execute or enqueue as needed:
    await generate_differential.execute(simulation=simulation)
```

---

## Summary

✅ **Minimum required**
- Define an async function
- Decorate with `@llm_service`
- Use identity mixins (recommended)
- Implement nothing if default flow suffices

✅ **Optional**
- Add prompt plan, codec overrides, or lifecycle hooks

✅ **Execution**
```python
await generate_initial.execute(simulation=my_sim)
```

---

© 2025 Jackfruit SimWorks • simcore_ai_django
