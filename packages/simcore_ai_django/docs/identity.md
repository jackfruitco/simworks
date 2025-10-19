# Identity System (simcore_ai_django)

> How `(origin, bucket, name)` stitches Services, Codecs, Prompt Sections, and Schemas together — with zero boilerplate.

The **tuple3 identity** model is the backbone of `simcore_ai_django`. When your **Service**, **PromptSection**, **Codec**, and **Response Schema** all share the same identity, the framework wires them together automatically.

```
(origin, bucket, name)  →  "origin.bucket.name"
```

Examples:
- `chatlab.standardized_patient.initial`
- `trainerlab.triage.reply`
- `simcore.feedback.create`

---

## Overview

- **Origin**: logical project or producer (e.g., your Django **app label**)
- **Bucket**: functional grouping (e.g., `standardized_patient`, `triage`, `feedback`)
- **Name**: concrete operation (snake-cased from your class name, minus common tokens)

All four building blocks (Service, Codec, PromptSection, Schema) carry the same identity so they can find each other without extra configuration.

---

## Autoderive Rules (Django)

`simcore_ai_django` extends the core identity utilities so classes can **autoderive** their identity:

- **origin** → Django **app label** (e.g., `"chatlab"`)
- **bucket** → `"default"` unless set on the class or provided by a mixin
- **name** → stripped & snake-cased class name

### Edge‑only token stripping

Name derivation strips common tokens from the **leading and trailing** edges of your class name (not the middle), repeatedly, then converts the remaining text to snake_case.

**Default core tokens:**
```
Codec, Service, Prompt, PromptSection, Section, Response, Generate, Output, Schema
```

**Django adds:**
- Your **app label** and common case variants (e.g., `Chatlab`, `CHATLAB`)
- Any tokens you add globally or per app (see below)

> We intentionally strip only at the **edges** to avoid mangling words like “Outpatient”.

### Global tokens (settings)

You can extend the tokens via Django settings:

```python
# settings.py
AI_IDENTITY_STRIP_TOKENS = {"Mixin", "LLM", "DTO"}
```

### Per‑app tokens (`apps.py`)

Each app can provide additional strip tokens:

```python
# chatlab/apps.py
from django.apps import AppConfig

class ChatlabConfig(AppConfig):
    name = "chatlab"
    identity_strip_tokens = {"Patient"}  # e.g., strip “Patient” from edges
```

These will be unioned with core + app-label tokens at runtime.

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
- Keep `origin`/`bucket` consistent across Services, Codecs, Sections, and Schemas
- Let `name` auto-derive from the class (after token stripping)
- Reduce boilerplate and avoid mistakes

---

## Collision Policy (DEBUG vs Production)

If two different classes derive the **exact same** identity in the **same registry**:

- **DEBUG=True** (or `SIMCORE_AI_DEBUG=1`): **raise** an error to catch the issue early
- **Production**: log a **warning**, then suffix the **name** with `-2`, `-3`, … until unique
  - e.g., `chatlab.standardized_patient.initial-2`

> You can test derivations in isolation with `Class.identity_tuple()` and confirm registries during startup.

---

## Inspecting & Debugging Identities

Every identity-aware class supports an inspection method:

```python
print(MyService.identity_tuple())        # ('chatlab', 'standardized_patient', 'initial')
print(MyCodec.identity_tuple())          # ditto
print(MyPromptSection.identity_tuple())  # ditto
print(MySchema.identity_tuple())         # ditto
```

And you can parse/build canonical strings:

```python
from simcore_ai.identity import parse_dot_identity

origin, bucket, name = parse_dot_identity("chatlab.standardized_patient.initial")
```

---

## Minimal Examples (All Four Types)

When all four share the same identity, the service can run with almost no config.

```python
# mixins.py
from simcore_ai_django.identity.mixins import DjangoIdentityMixin

class ChatlabMixin(DjangoIdentityMixin): origin = "chatlab"
class StandardizedPatientMixin(DjangoIdentityMixin): bucket = "standardized_patient"
```

```python
# schemas/patient.py
from simcore_ai_django.api.types import DjangoStrictSchema, DjangoLLMResponseItem

class PatientInitialOutputSchema(DjangoStrictSchema, ChatlabMixin, StandardizedPatientMixin):
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
from simcore_ai_django.services.base import DjangoExecutableLLMService

@llm_service
class GenerateInitialResponse(DjangoExecutableLLMService, ChatlabMixin, StandardizedPatientMixin):
    # Optional today until schema-by-identity is enabled globally:
    from chatlab.ai.schemas import PatientInitialOutputSchema as _Schema
    response_format_cls = _Schema
    pass
```

**Resulting identity:** `chatlab.standardized_patient.initial` for all four.

---

## Frequently Asked Questions

### Do I have to use mixins?
No. You can set `origin`/`bucket`/`name` as **class attributes** directly. Mixins just reduce repetition and ensure consistency.

### Can I override the `name`?
Yes — set `name = "my_snake_name"` on the class to bypass auto-derivation.

### Can I use decorators to override identity?
Yes. The Django-aware decorators (`@llm_service`, `@codec`, `@prompt_section`) accept classes that already carry identity attrs or mixins. Prefer class-level attrs/mixins for clarity.

### What about schema-by-identity?
If enabled, codecs/services will auto-resolve schemas with the same tuple3. Until then, set `response_format_cls` on services explicitly.

---

## Tips for Large Apps

- Define a small set of identity mixins per domain (e.g., `StandardizedPatientMixin`, `TriageMixin`).
- Add per-app strip tokens in `apps.py` to keep names concise (e.g., strip `Patient`, `Scenario`).
- In tests, assert identity alignment across all types for each operation.

```python
assert Svc.identity_tuple() == Codec.identity_tuple() == Sec.identity_tuple() == Schema.identity_tuple()
```

---

## See Also

- [Quick Start](quick_start.md)
- [Services](services.md)
- [Codecs](codecs.md)
- [Schemas](schemas.md)
- [Prompt Sections](prompt_sections.md)
- [Prompts & Plans](prompts.md)
