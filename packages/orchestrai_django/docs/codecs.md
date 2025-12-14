# Codecs in simcore_ai_django

> Codecs bridge the gap between raw AI responses and structured Django data.

---

## Overview

A **Codec** is responsible for:
- Parsing the structured response returned by an LLM
- Validating it against a **Response Schema**
- Persisting the parsed data into your Django models or other stores

When your Codec shares the same **tuple3 identity** as a Service, PromptSection, and Schema,
it is discovered and linked automatically.

---

## Base Classes

| Class | Description |
|:--|:--|
| `BaseCodec` | Provider‑agnostic logic (in `simcore_ai`) |
| `DjangoBaseCodec` | Django‑aware codec base (with persistence hooks and identity autoderivation) |

---

## Decorator

```python
from simcore_ai_django.api.decorators import codec
```

The `@codec` decorator:
- Registers your codec **class** with the Django codec registry
- Ensures proper tuple³ identity (origin, bucket, name)
- Applies collision-safe renaming (e.g., `name-2`) when necessary
- Enables automatic linking to matching Service/Prompt/Schema by tuple³ identity

---

## Minimal Example

```python
from simcore_ai_django.api.decorators import codec
from simcore_ai_django.api.types import DjangoBaseCodec


@codec
# dev: if SIMCORE_AI_VALIDATE_CODECS_ON_REGISTER is true, a shallow instantiation is attempted
class PatientInitialResponseCodec(DjangoBaseCodec):
    def persist(self, *, response, parsed) -> dict:
        # Save AI input, metadata, or computed results
        return {"ok": True}
```

✅ This class will automatically match a Service, Prompt, and Schema
with the same tuple3 identity (e.g., `chatlab.standardized_patient.initial`).

---

## Identity Autoderivation

Just like Services and Schemas, Codecs derive their identity automatically:

| Field | Resolution |
|:--|:--|
| **origin** | Django app label |
| **bucket** | `"default"` unless provided or inherited (services and codecs default to `"default"`) |
| **name** | Stripped & snake‑cased class name (edges only) |

Token stripping includes core tokens (Prompt, Section, Service, Codec, Generate, Response, Mixin), plus Django and any app/settings-provided tokens (AppConfig.AI_IDENTITY_STRIP_TOKENS, settings.SIMCORE_AI_IDENTITY_STRIP_TOKENS). Mixins do not influence the derived name.

### Example with Mixins

```python
from chatlab.ai.mixins import ChatlabMixin, StandardizedPatientMixin

@codec
class PatientInitialResponseCodec(DjangoBaseCodec, ChatlabMixin, StandardizedPatientMixin):
    pass
```

→ Identity: `chatlab.standardized_patient.initial`

---

## Persistence Flow

1. The LLM provider returns a structured response (already validated)
2. The Codec:
   - Calls `persist()` with `(response, parsed)`
   - Optionally enriches, normalizes, or stores data
   - Returns a summary dict for trace or UI feedback

### Example

```python
def persist(self, *, response, parsed):
    patient = response.simulation.patient
    db_record = PatientFeedback.objects.create(
        simulation=response.simulation,
        correct_diagnosis=parsed.metadata.correct_diagnosis.value,
        correct_treatment_plan=parsed.metadata.correct_treatment_plan.value,
        overall_feedback=parsed.metadata.overall_feedback.value,
    )
    return {"feedback_id": db_record.pk}
```

---

## Validation

Codecs automatically validate AI responses using the matching **Response Schema**.
If validation fails:
- In **DEBUG mode** → Raises `ValidationError`
- In **production** → Logs structured error, discards invalid payload

You can override `validate_response()` if you need to preprocess data first.

---

## Advanced Example

```python
from simcore_ai_django.api.decorators import codec
from simcore_ai_django.api.types import DjangoBaseCodec


@codec
class PatientResultsCodec(DjangoBaseCodec):
    async def persist(self, *, response, parsed):
        for item in parsed.metadata.results:
            await persist_result(response.simulation, item)
        return {"count": len(parsed.metadata.results)}
```

---

## Debugging and Inspection

```python
print(MyCodec.identity_tuple())  # ('chatlab', 'standardized_patient', 'initial')
print(MyCodec.identity_str())    # 'chatlab.standardized_patient.initial'
```

To see all registered codecs:

```python
from simcore_ai_django.components.codecs import CodecRegistry

# Check whether a codec is registered by identity
print(CodecRegistry.has("chatlab", "standardized_patient", "initial"))
```

---

## Summary

✅ **Minimum required**
- Subclass `DjangoBaseCodec`
- Decorate with `@codec`
- Implement a `persist()` method

✅ **Automatic**
- Identity autoderivation (Django-aware)
- Collision-safe registration (suffixing when needed)
- Schema validation
- Optional dev-time constructibility check (SIMCORE_AI_VALIDATE_CODECS_ON_REGISTER)

✅ **Optional**
- Mixins for shared origin/bucket
- Custom validation or persistence logic

---

## Related Docs

- [Services](services.md)
- [Schemas](schemas.md)
- [Prompt Sections](prompt_sections.md)
- [Identity System](identity.md)
