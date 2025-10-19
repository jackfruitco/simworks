# Decorators — simcore_ai_django

> Reference for Django-aware decorators that register and auto-wire Services, Codecs, and Prompt Sections.

---

## Overview

`simcore_ai_django` provides three primary decorators:

| Decorator | Applies To | Purpose |
|---|---|---|
| `@llm_service` | **Service class** | Register an executable LLM service and ensure identity autoderivation |
| `@codec` | **Codec class** | Register a codec that validates & persists LLM responses |
| `@prompt_section` | **PromptSection class** | Register a prompt building block discoverable by the Prompt Engine |

All three decorators are **identity-aware**: they cooperate with Django’s autoderive rules so that
`origin.bucket.name` is derived consistently and the pipeline can wire itself automatically.

---

## Identity Recap

The shared tuple3 identity is:

```
(origin, bucket, name) → "origin.bucket.name"
```

- **origin**: your Django app label (e.g., `chatlab`), unless overridden
- **bucket**: `"default"` unless set on the class or via mixin
- **name**: class name stripped of edge tokens and snake-cased

Use **identity mixins** to keep `origin` and `bucket` consistent across types:

```python
from simcore_ai_django.identity.mixins import DjangoIdentityMixin

class ChatlabMixin(DjangoIdentityMixin):
    origin = "chatlab"

class StandardizedPatientMixin(DjangoIdentityMixin):
    bucket = "standardized_patient"
```

---

## `@llm_service`

### Purpose
Registers a **DjangoExecutableLLMService** (or compatible base) with identity, enabling `.execute()`/`.enqueue()` and automatic resolution of prompt, codec, and (optionally) schema.

### Usage (class-based — recommended)
```python
from simcore_ai_django.api.decorators import llm_service
from simcore_ai_django.api.types import DjangoExecutableLLMService
from chatlab.ai.mixins import ChatlabMixin, StandardizedPatientMixin

@llm_service
class GenerateInitialResponse(DjangoExecutableLLMService, ChatlabMixin, StandardizedPatientMixin):
    # Optional today until schema-by-identity is enabled globally
    from chatlab.ai.schemas import PatientInitialOutputSchema as _Schema
    response_format_cls = _Schema
    pass
```

### Identity Behavior
- If `origin/bucket/name` are not set on the class, they’re autoderived using **DjangoIdentityMixin** rules (app label, default bucket, stripped class name).
- If multiple services collide on the exact identity:
  - **DEBUG**: raise
  - **Prod**: warn and suffix name (`-2`, `-3`, …)

### Optional Keyword Overrides
Depending on your installed version of the decorator, you may pass optional keywords that are **merged** with class-derived identity:
```python
@llm_service(origin="chatlab", bucket="standardized_patient", name="initial")
class GenerateInitialResponse(...):
    ...
```
> If present, these override the class’ autoderived parts. If omitted, class/mixin attributes win.

### Notes
- The decorator **must** be applied to a class (for Django). Function-level services are a core (`simcore_ai`) feature and not commonly used in Django projects.
- The service will default `prompt_plan` to the **PromptSection** that matches its identity if you don’t specify a custom plan.

---

## `@codec`

### Purpose
Registers a **DjangoBaseLLMCodec** that validates model output against a schema and persists it.

### Usage
```python
from simcore_ai_django.api.decorators import codec
from simcore_ai_django.api.types import DjangoBaseLLMCodec
from chatlab.ai.mixins import ChatlabMixin, StandardizedPatientMixin

@codec
class PatientInitialCodec(DjangoBaseLLMCodec, ChatlabMixin, StandardizedPatientMixin):
    def persist(self, *, response, parsed) -> dict:
        # create domain objects; return summary info
        return {"ok": True}
```

### Identity Behavior
- Same autoderive rules as services (origin from app label, default bucket, stripped class name).
- When identity matches a **Service** and **Schema**, this codec is selected automatically.

### Tips
- Keep validation in the **Schema**; keep persistence in the **Codec**.
- If schema-by-identity is not enabled globally, the **Service** should set `response_format_cls` explicitly.

---

## `@prompt_section`

### Purpose
Registers a **PromptSection** (PromptKit) in the global registry for the Prompt Engine to compose prompts.

### Usage
```python
from simcore_ai_django.api.decorators import prompt_section
from simcore_ai_django.api.types import PromptSection
from chatlab.ai.mixins import ChatlabMixin, StandardizedPatientMixin

@prompt_section
class PatientInitialSection(PromptSection, ChatlabMixin, StandardizedPatientMixin):
    instruction = "You are a standardized patient in a telemedicine chat."
    message = "Begin the conversation naturally in first-person tone."
```

### Identity Behavior
- Autoderived identity links this section to the matching **Service** automatically when no custom `prompt_plan` is provided.

### Dynamic Sections
```python
@prompt_section
class PatientFollowupSection(PromptSection, ChatlabMixin):
    bucket = "standardized_patient"

    async def arender(self, simulation, **ctx) -> str:
        return f"Patient reports continued {getattr(simulation, 'chief_complaint', 'unknown symptoms')}."
```

---

## Error Handling & Diagnostics

- **Collision Policy**: In DEBUG, duplicate identity registration raises immediately; in production, the name is auto-suffixed.
- **Introspection**:
  ```python
  print(GenerateInitialResponse.identity_tuple())
  print(PatientInitialCodec.identity_str())
  print(PatientInitialSection.identity_tuple())
  ```
- **Registries**:
  ```python
  from simcore_ai.promptkit.registry import PromptRegistry
  print([c.__name__ for c in PromptRegistry.all()])
  ```

---

## Migration Notes

- If you’re migrating from older decorator forms:
  - Prefer **class-based** `@llm_service` for Django.
  - Remove legacy `namespace` or tuple2 (`bucket:name`) usages — **dot-only tuple3** is the standard.
  - Keep imports via the `api` facade for forward compatibility:
    ```python
    from simcore_ai_django.api.decorators import llm_service, codec, prompt_section
    from simcore_ai_django.api.types import DjangoExecutableLLMService, DjangoBaseLLMCodec, PromptSection, DjangoStrictSchema
    ```

---

## Testing Tips

- Assert identity alignment in unit tests:
  ```python
  assert Svc.identity_tuple() == Codec.identity_tuple() == Sec.identity_tuple()
  ```
- Ensure modules are **imported** in test setup (so decorators register classes).
- In DEBUG tests, assert that collisions raise; in non-DEBUG, assert `-2` suffixing.

---

## Summary

- `@llm_service` — registers executable services and wires identity
- `@codec` — registers persistence with identity-aware selection
- `@prompt_section` — registers prompt building blocks

With identity mixins and edge-only token stripping, most boilerplate disappears — components connect themselves by `origin.bucket.name`.

---

© 2025 Jackfruit SimWorks • simcore_ai_django
