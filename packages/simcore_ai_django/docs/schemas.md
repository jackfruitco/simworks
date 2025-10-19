# Response Schemas in simcore_ai_django

> Define strict, Pydantic‑based schemas that validate AI output and align by identity.

---

## Overview

A **Response Schema** describes the structured output expected from the LLM.  
In `simcore_ai_django`, schemas:

- Inherit from **`DjangoStrictSchema`** (Pydantic model + Django‑aware identity)
- Participate in the **tuple3 identity** system (`origin.bucket.name`)
- Are discovered automatically by **Codecs** and **Services** when identities match
- Remain framework‑agnostic for pure validation (persistence lives in Codecs)

---

## Base Class

```python
from simcore_ai_django.api.types import DjangoStrictSchema
```

`DjangoStrictSchema`:
- Extends Pydantic’s strict model behavior
- Mixes in `DjangoIdentityMixin` so `(origin, bucket, name)` autoderive from:
  - **origin** → Django app label
  - **bucket** → `"default"` (unless set or provided by mixin)
  - **name** → stripped + snake‑case of class name (edge‑only token removal)

---

## Minimal Example

```python
from simcore_ai_django.api.types import DjangoStrictSchema, DjangoLLMResponseItem

class PatientInitialOutputSchema(DjangoStrictSchema):
    messages: list[DjangoLLMResponseItem]
```

✅ Identity autoderives (e.g., `chatlab.standardized_patient.initial`) assuming your app/mixins set origin/bucket appropriately.

---

## Identity Mixins (Recommended)

```python
from simcore_ai_django.identity.mixins import DjangoIdentityMixin

class ChatlabMixin(DjangoIdentityMixin):
    origin = "chatlab"

class StandardizedPatientMixin(DjangoIdentityMixin):
    bucket = "standardized_patient"


class PatientInitialOutputSchema(DjangoStrictSchema, ChatlabMixin, StandardizedPatientMixin):
    messages: list[DjangoLLMResponseItem]
```

Resulting identity:
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

Use `DjangoBaseOutputItem` for key/value leaf nodes and `DjangoBaseOutputBlock` for grouped fields.  
Blocks do **not** require an identity.

### Full Schema

```python
class HotwashInitialSchema(DjangoStrictSchema):
    metadata: FeedbackBlock
```

---

## Token Stripping (edge‑only)

Class name → `name` uses edge‑only token removal, then snake‑case.

**Core defaults:** `{"Codec","Service","Prompt","PromptSection","Section","Response","Generate","Output","Schema"}`

**Django adds:** your app label variants + custom tokens from:
- `settings.AI_IDENTITY_STRIP_TOKENS`
- `apps.py`: `identity_strip_tokens = {"Patient", ...}`

> Edge‑only stripping avoids altering middle words like “Outpatient”.

---

## Linking with Codecs and Services

When identities match, the framework wires components automatically:

- **Codec** with the same tuple3 → used for parse/validate/persist
- **Service** with the same tuple3 → will resolve the matching schema via the codec
- **PromptSection** → participates in the same identity to build prompts

> If schema-by-identity is not globally enabled in your build, set it explicitly on the Service:
> ```python
> class MyService(...):
>     from my_app.ai.schemas import MySchema as _Schema
>     response_format_cls = _Schema
> ```

---

## Validation Behavior

Schemas are strict:
- Unknown fields are rejected
- Type mismatches raise errors
- Helpful error messages for debugging in **DEBUG**

You can include Pydantic validators for advanced logic.

```python
from pydantic import field_validator

class MySchema(DjangoStrictSchema):
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

- Use **mixins** per domain (e.g., `StandardizedPatientMixin`, `TriageMixin`)
- Keep schemas focused on validation; use Codecs for persistence
- Break large schemas into **items** and **blocks** for clarity
- Add per‑app strip tokens to keep names concise

---

## Related Docs

- [Identity System](identity.md)
- [Services](services.md)
- [Codecs](codecs.md)
- [Prompt Sections](prompt_sections.md)
- [Prompts & Prompt Plans](prompts.md)

---

© 2025 Jackfruit SimWorks • simcore_ai_django
