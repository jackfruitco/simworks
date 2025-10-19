# SimWorks AI Service Quickstart Guide

This guide explains how to create a fully functional AI service in SimWorks using the new **tuple3 identity** model.

---

## 🧩 Overview

Each AI pipeline (service → prompt → codec → schema) is automatically linked by the shared identity tuple:

```
(origin, bucket, name)
```

If all components share the same tuple3 identity, they work together automatically — no extra configuration required.

---

## 1️⃣ Response Schema

### Base Class
`DjangoStrictSchema`

### Minimum Definition
Define your output fields only.

```python
from simcore_ai_django.api.types import DjangoStrictSchema, DjangoLLMResponseItem

class PatientInitialOutputSchema(DjangoStrictSchema):
    messages: list[DjangoLLMResponseItem]
```

✅ **Identity** auto-derives from Django app, class name, and mixins.

---

## 2️⃣ Prompt Section

### Base Class
`PromptSection`

### Minimum Definition
Provide either a static `instruction` or a custom render method.

```python
from simcore_ai_django.api.decorators import prompt_section
from simcore_ai_django.promptkit import PromptSection

@prompt_section
class InitialSection(PromptSection):
    instruction: str = "Write the first SMS message in character..."
```

✅ **Identity** auto-derives via Django rules (e.g. `chatlab.standardized_patient.initial`).

---

## 3️⃣ Codec

### Base Class
`DjangoBaseLLMCodec`

### Minimum Definition
Implement a `persist()` method.

```python
from simcore_ai_django.api.decorators import codec
from simcore_ai_django.codecs import DjangoBaseLLMCodec

@codec
class InitialCodec(DjangoBaseLLMCodec):
    def persist(self, *, response, parsed) -> dict:
        # Persist messages, metadata, results, etc.
        return {"ai_response_id": 123}
```

✅ Automatically validates against the matching schema.

---

## 4️⃣ Service

### Base Class
`DjangoExecutableLLMService`

### Minimum Definition
Usually no overrides needed.

```python
from simcore_ai_django.api.decorators import llm_service
from simcore_ai_django.services.base import DjangoExecutableLLMService

@llm_service
class GenerateInitialResponse(DjangoExecutableLLMService):
    pass
```

✅ Automatically resolves:
- the prompt section with matching tuple3 identity
- the codec with matching tuple3 identity
- the schema (explicit today, implicit soon)

---

## ⚙️ Execution Flow

```python
await GenerateInitialResponse.execute(simulation=my_sim)
```

1. Identity auto-derives (`chatlab.standardized_patient.initial`)
2. Prompt resolved via registry
3. Messages built → request sent to provider
4. Codec validates and persists results
5. Returns structured AI response

---

## 🔍 Tip

To verify your setup, print identities:

```python
print(MyService.identity_tuple())
print(MyPromptSection.identity_tuple())
print(MyCodec.identity_tuple())
print(MySchema.identity_tuple())
```

They should all match.

---

## ✅ Minimal Working Chain Example

```
chatlab.standardized_patient.initial
├── GenerateInitialResponse   (Service)
├── ChatlabPatientInitialSection   (Prompt)
├── PatientInitialResponseCodec   (Codec)
└── PatientInitialOutputSchema   (Schema)
```

That’s all you need for a complete `.execute()` cycle.