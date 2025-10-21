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
`DjangoBaseOutputSchema`

### Minimum Definition
Define your output fields only.

```python
from simcore_ai_django.api.types import DjangoBaseOutputSchema, DjangoLLMResponseItem

class PatientInitialOutputSchema(DjangoBaseOutputSchema):
    messages: list[DjangoLLMResponseItem]
```
Tip: To align identities across all components without extra wiring, add identity mixins (e.g., ChatlabMixin, StandardizedPatientMixin) or set origin/bucket as class attrs. Otherwise, the Django autoderive rules will use your app label for origin, default for bucket, and a stripped/snake class name for name.

✅ **Identity** auto-derives from Django app, class name, and mixins.

---

## 2️⃣ Prompt Section

### Base Class
`PromptSection`

### Minimum Definition
Provide either a static `instruction` or a custom render method.

```python
from simcore_ai_django.api.decorators import prompt_section
from simcore_ai_django.api.types import PromptSection

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
from simcore_ai_django.api.types import DjangoBaseLLMCodec

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

@llm_service  # or: @llm_service(origin="chatlab", bucket="standardized_patient", name="initial")
async def generate_initial(simulation, slim):
    # Call automatically links to matching prompt, codec, and schema
    print("✅ AI service executed successfully")
    return {"ok": True}
```

✅ Automatically resolves:
- the `PromptSection` with matching tuple³ identity
- the `Codec` with matching tuple³ identity
- the `Schema` (explicit today, implicit soon)

---

## ⚙️ Execution Flow

```python
await generate_initial.execute(simulation=my_sim)
```

1. Identity auto-derives (e.g., chatlab.standardized_patient.initial)  
2. Prompt resolved via registry  
3. Messages built → request sent to provider  
4. Codec validates, persists results, and schema validates output  
5. Returns structured AI response  

---

## 🔍 Tip

To verify your setup, print identities:

```python
print(generate_initial.identity_tuple())
print(InitialSection.identity_tuple())
print(InitialCodec.identity_tuple())
print(PatientInitialOutputSchema.identity_tuple())
```

They should all match.

---

## ✅ Minimal Working Chain Example

```
chatlab.standardized_patient.initial
├── generate_initial           (Service)
├── ChatlabPatientInitialSection   (Prompt)
├── PatientInitialResponseCodec    (Codec)
└── PatientInitialOutputSchema     (Schema)
```

That’s all you need for a complete `.execute()` cycle.
