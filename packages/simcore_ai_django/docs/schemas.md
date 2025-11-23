# Schemas in simcore_ai_django

> Define strict, Pydantic-based schemas that validate AI output and align by identity.

---

## Overview

A **Response Schema** describes the structured output expected from the LLM. In `simcore_ai_django`, schemas:

- Inherit from **`DjangoBaseOutputSchema`** (a strict Pydantic model with Django-aware identity helpers).
- Participate in the **tuple³ identity** system (`origin.bucket.name`).
- Are discovered automatically by **Codecs** and **Services** when identities match.
- Remain focused on validation; persistence stays inside Codecs.

---

## Base Classes

```python
from simcore_ai_django.api.types import (
    DjangoBaseOutputSchema,
    DjangoBaseOutputBlock,
    DjangoBaseOutputItem,
    DjangoOutputItem,
)
```

- Use `DjangoBaseOutputSchema` for top-level response models.
- Use `DjangoBaseOutputBlock` for nested structured groups (no identity required).
- Use `DjangoBaseOutputItem` for key/value pairs inside blocks.

---

## Minimal Example

```python
from simcore_ai_django.api.types import DjangoBaseOutputSchema, DjangoOutputItem


class PatientInitialOutputSchema(DjangoBaseOutputSchema):
    messages: list[DjangoOutputItem]
```

Identity autoderives (e.g., `chatlab.standardized_patient.initial`) when your app or mixins define `origin`/`bucket`.

---

## Identity Mixins (Recommended)

```python
from simcore_ai_django.identity.mixins import DjangoIdentityMixin

class ChatlabMixin(DjangoIdentityMixin):
    origin = "chatlab"

class StandardizedPatientMixin(DjangoIdentityMixin):
    bucket = "standardized_patient"


class PatientInitialOutputSchema(DjangoBaseOutputSchema, ChatlabMixin, StandardizedPatientMixin):
    messages: list[DjangoOutputItem]
```

Identity resolves to:

```
chatlab.standardized_patient.initial
```

---

## Structuring Complex Schemas

You can compose items and blocks for clarity and strong typing.

### Items and Blocks

```python
from typing import Literal
from pydantic import Field
from simcore_ai_django.api.types import DjangoBaseOutputItem, DjangoBaseOutputBlock


class CorrectDiagnosisItem(DjangoBaseOutputItem):
    key: Literal["correct_diagnosis"] = Field(...)
    value: bool


class FeedbackBlock(DjangoBaseOutputBlock):
    correct_diagnosis: CorrectDiagnosisItem
```

Blocks do **not** require an identity.

### Full Schema

```python
class HotwashInitialSchema(DjangoBaseOutputSchema):
    metadata: FeedbackBlock
```

---

## Token Stripping (edge-only)

Class name → `name` uses edge-only token removal, then snake_case.

**Core defaults:** `{ "Prompt", "Section", "Service", "Codec", "Generate", "Response", "Mixin" }`

**Django adds:** `"Django"`, app label variants, and optional tokens from:
- `settings.AI_IDENTITY_STRIP_TOKENS`
- `AppConfig.identity_strip_tokens` or `AppConfig.AI_IDENTITY_STRIP_TOKENS`

> Edge-only stripping avoids altering middle words like “Outpatient”.

---

## Linking with Codecs and Services

When identities match, the framework wires components automatically:

- **Codec** with the same tuple³ → used for parse/validate/persist.
- **Service** with the same tuple³ → resolves the matching codec and schema via registries.
- **PromptSection** → participates in the same identity to build prompts.

If your build does not enable schema-by-identity globally, set it explicitly on the Service:

```python
class MyService(...):
    from my_app.ai.schemas import MySchema as _Schema
    response_format_cls = _Schema
```

---

## Validation Behavior

Schemas are strict:

- Unknown fields are rejected.
- Type mismatches raise errors.
- Helpful error messages in **DEBUG** environments.

You can include Pydantic validators for advanced logic.

```python
from pydantic import field_validator

class MySchema(DjangoBaseOutputSchema):
    score: int

    @field_validator("score")
    @classmethod
    def _check_score(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("score must be within 0..100")
        return v
```

---

## Debugging Identity

```python
print(PatientInitialOutputSchema.identity_tuple())  # ('chatlab','standardized_patient','initial')
print(PatientInitialOutputSchema.identity_str())    # 'chatlab.standardized_patient.initial'
```

---

## Best Practices

- Use **mixins** per domain (e.g., `StandardizedPatientMixin`, `TriageMixin`).
- Keep schemas focused on validation; use Codecs for persistence.
- Break large schemas into **items** and **blocks** for clarity.
- Add per-app strip tokens to keep names concise.

---

## Related Docs

- [Identity System](identity.md)
- [Services](services.md)
- [Codecs](codecs.md)
- [Prompt Sections](prompt_sections.md)
- [Prompts & Prompt Plans](prompts.md)

---

© 2025 Jackfruit SimWorks • simcore_ai_django
