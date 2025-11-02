# Identity System (simcore_ai_django)

> How `(origin, bucket, name)` stitches Services, Codecs, Prompt Sections, and Schemas together — with minimal configuration.

The **tuple³ identity** model is the backbone of `simcore_ai_django`. When your **Service**, **PromptSection**, **Codec**, and **Response Schema** all share the same identity, the framework wires them together automatically.

```
(origin, bucket, name)  →  "origin.bucket.name"
```

Examples:
- `chatlab.standardized_patient.initial`
- `trainerlab.triage.reply`
- `simcore.feedback.create`

---

## Overview

- **Origin**: logical project or producer (typically your Django **app label**).
- **Bucket**: functional grouping (e.g., `standardized_patient`, `triage`, `feedback`).
- **Name**: concrete operation (derived from the class name after token stripping).

All four building blocks (Service, Codec, PromptSection, Schema) carry the same identity so they can find each other without extra configuration.

---

## Autoderive Rules (Django)

`simcore_ai_django` extends the core identity utilities so classes can **autoderive** their identity:

- **origin** → Django **app label** when available (falls back to module root → `"default"`).
- **bucket** → `"default"` unless set on the class/mixin or provided explicitly.
- **name** → class name with edge tokens stripped and converted to snake_case.

### Edge-only token stripping

Name derivation removes tokens from the **leading and trailing** edges of your class name (not the middle), then converts the remainder to snake_case.

**Default core tokens:**
```
Prompt, Section, Service, Codec, Generate, Response, Mixin
```

**Django adds:**
- `"Django"`
- Variants of your **app label** (case and slug forms)
- Global tokens from `settings.AI_IDENTITY_STRIP_TOKENS`
- App-specific tokens from `AppConfig.identity_strip_tokens` or `AppConfig.AI_IDENTITY_STRIP_TOKENS`
- Any extra tokens supplied by mixins/decorators

> We intentionally strip only at the edges to avoid mangling words like “Outpatient”.

---

## Identity Mixins

Use mixins to **fix** identity parts across multiple classes:

```python
# chatlab/ai/mixins.py
from simcore_ai_django.identity.mixins import DjangoIdentityMixin

class ChatlabMixin(DjangoIdentityMixin):
    origin = "chatlab"

class StandardizedPatientMixin(DjangoIdentityMixin):
    bucket = "standardized_patient"
```

Then apply them to your types:

```python
@prompt_section
class ChatlabPatientInitialSection(PromptSection, ChatlabMixin, StandardizedPatientMixin):
    instruction = "..."  # name auto-derives to "initial"
```

**Why mixins?**
- Keep `origin`/`bucket` consistent across Services, Codecs, Sections, and Schemas.
- Let `name` autoderive from the class (after token stripping).
- Reduce boilerplate and avoid mistakes.

---

## Collision Policy (DEBUG vs Production)

If two different classes/functions resolve to the **same** identity in the **same** registry, the framework will defer to `resolve_collision_django`:

- **`settings.DEBUG` True** → raises immediately.
- **`settings.DEBUG` False** → logs and suffixes the name with `-2`, `-3`, ….

This behavior keeps startup robust while still surfacing issues early in development.

---

## Inspecting & Debugging Identities

Every identity-aware class supports inspection helpers:

```python
print(MyService.identity_tuple())        # ('chatlab', 'standardized_patient', 'initial')
print(MyCodec.identity_tuple())          # ditto
print(MyPromptSection.identity_tuple())  # ditto
print(MySchema.identity_tuple())         # ditto
```

And you can parse/build canonical strings:

```python
from simcore_ai_django.identity import parse_dot_identity

origin, bucket, name = parse_dot_identity("chatlab.standardized_patient.initial")
```

You can also derive identities directly without registering:

```python
from simcore_ai_django.identity import derive_django_identity_for_class
print(derive_django_identity_for_class(MyPromptSection))
```

---

## Minimal Examples (All Four Types)

When all four share the same identity, the service can run with almost no configuration.

```python
# mixins.py
from simcore_ai_django.identity.mixins import DjangoIdentityMixin

class ChatlabMixin(DjangoIdentityMixin): origin = "chatlab"
class StandardizedPatientMixin(DjangoIdentityMixin): bucket = "standardized_patient"
```

```python
# schemas/patient.py
from simcore_ai_django.api.types import DjangoBaseOutputSchema, DjangoLLMResponseItem

class PatientInitialOutputSchema(DjangoBaseOutputSchema, ChatlabMixin, StandardizedPatientMixin):
    messages: list[DjangoLLMResponseItem]
```

```python
# prompts/chatlab_base.py
from simcore_ai_django.api.decorators import prompt_section
from simcore_ai_django.promptkit import PromptSection

@prompt_section
class ChatlabPatientInitialSection(PromptSection, ChatlabMixin, StandardizedPatientMixin):
    instruction = "Write the opening SMS message..."
```

```python
# codecs/patient.py
from simcore_ai_django.api.decorators import codec
from simcore_ai_django.codecs import DjangoBaseLLMCodec

@codec
class PatientInitialResponseCodec(ChatlabMixin, StandardizedPatientMixin, DjangoBaseLLMCodec):
    def persist(self, *, response, parsed) -> dict:
        # Persist response & first assistant message...
        return {"ok": True}
```

```python
# services/patient.py
from simcore_ai_django.api.decorators import llm_service

@llm_service  # or: @llm_service(namespace="chatlab", kind="standardized_patient", name="initial")
async def generate_initial(simulation, slim):
    return {"ok": True}
```

**Resulting identity:** `chatlab.standardized_patient.initial` for all four.

---

## Frequently Asked Questions

**How do I override only the bucket?**
> Provide `bucket="triage"` on the decorator or mix it in via `DjangoIdentityMixin`.

**Can I see all registered identities?**
> Use registry helpers such as `PromptRegistry.all()` or `CodecRegistry.names()`.

**Do schemas require decorators?**
> No. Schemas inherit from `DjangoBaseOutputSchema` and autoderive identity based on mixins/class name.

---

© 2025 Jackfruit SimWorks • simcore_ai_django
