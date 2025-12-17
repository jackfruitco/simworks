# Persistence with Codecs — simcore_ai_django

> How to validate AI output with Schemas and **persist** results with Codecs in Django.

---

## Overview

In `simcore_ai_django`, **Codecs** are responsible for:
1. **Validating** the LLM response with a **Response Schema** (Pydantic)
2. **Persisting** validated data to your Django models
3. Returning a **lightweight summary** (e.g., IDs, counts) to the caller/UI

When your Codec shares the same **tuple4 identity** as the Service and Schema
(`origin.bucket.name`), the framework auto-wires them together.

---

## Where Persistence Happens

```
Service.execute()
  └─ send request to provider
       └─ validate response with Schema
            └─ Codec.persist(response=..., parsed=...)  ← You implement this
                 └─ return summary dict
```

- **`response`** is a transport object (contains identity, correlation id, etc.)
- **`parsed`** is the Pydantic model instance returned by your **Response Schema**
- Your Codec’s `persist()` method should **not** return ORM instances; return a small serializable dict

---

## Minimal Example

```python
from simcore_ai_django.api.decorators import codec
from simcore_ai_django.api.types import DjangoBaseCodec


@codec
class PatientInitialCodec(DjangoBaseCodec):
    def persist(self, *, response, parsed) -> dict:
        # example: save one message
        from chatlab.models import Message

        msg = Message.objects.create(
            simulation=response.simulation,
            role="patient",
            text=parsed.input[0].content if parsed.input else "",
            meta={"identity": response.identity_str},
        )
        return {"message_id": msg.id}
```

✅ The schema validation already happened before `persist()` is called.

---

## Transactions (`transaction.atomic`)

Use **atomic transactions** to ensure consistency:

```python
from django.db import transaction

@codec
class PatientResultsCodec(DjangoBaseCodec):
    def persist(self, *, response, parsed) -> dict:
        from chatlab.models import Result

        with transaction.atomic():
            count = 0
            for item in parsed.metadata.results:
                Result.objects.create(
                    simulation=response.simulation,
                    name=item.key,
                    value=item.value,
                )
                count += 1

        return {"results_created": count}
```

If an exception occurs anywhere inside the `with transaction.atomic()` block,
the entire persistence operation **rolls back**.

---

## Working with Related Models

```python
@codec
class EncounterCodec(DjangoBaseCodec):
    def persist(self, *, response, parsed) -> dict:
        from chatlab.models import Encounter, Observation

        enc = Encounter.objects.create(
            simulation=response.simulation,
            started_at=parsed.metadata.started_at,
            identity=response.identity_str,
        )

        Observation.objects.bulk_create([
            Observation(encounter=enc, kind=o.kind, value=o.value)
            for o in parsed.metadata.observations
        ])

        return {"encounter_id": enc.id, "obs_count": len(parsed.metadata.observations)}
```

> Prefer `bulk_create()` for large batches to minimize DB round-trips.

---

## Idempotency (Correlation IDs)

Every request has a **correlation_id**. Use it to **dedupe** on retries:

```python
from django.db import transaction, IntegrityError


@codec
class SafeCodec(DjangoBaseCodec):
    def persist(self, *, response, parsed) -> dict:
        from chatlab.models import AIResponse

        with transaction.atomic():
            obj, created = AIResponse.objects.get_or_create(
                correlation_id=response.request_correlation_id,
                defaults={
                    "simulation": response.simulation,
                    "namespace": response.namespace,
                    "kind": response.kind,
                    "name": response.name,
                    "payload": parsed.model_dump(),
                },
            )
        return {"ai_response_id": obj.id, "created": created}
```

- Use a **unique** constraint on `correlation_id` for safety.

---

## Signals After Persistence

You can emit your own domain signals after saving:

```python
from django.dispatch import Signal
encounter_saved = Signal()

@codec
class EncounterCodec(DjangoBaseCodec):
    def persist(self, *, response, parsed) -> dict:
        from chatlab.models import Encounter
        enc = Encounter.objects.create(...)
        encounter_saved.send(sender=self.__class__, encounter=enc, response=response)
        return {"encounter_id": enc.id}
```

Or handle the built-in **emitter** signals elsewhere to react to responses.

---

## Error Handling

- Exceptions in `persist()` should bubble up; the Service will emit `emit_failure(...)`
- In **DEBUG**, validation errors raise immediately  
- In **production**, failed validation is logged and the Codec may be skipped (config-dependent)

**Pro Tip:** Keep `persist()` small and predictable — do heavy work in domain services.

---

## Patterns for Clean Codecs

- **Keep parsing/validation in Schemas**; don’t duplicate checks in Codecs
- Return **small dicts**: IDs, counters, flags
- Prefer **atomic** blocks and **bulk_create**
- Use **correlation_id** to avoid duplicates
- Avoid returning ORM objects (not JSON-safe)

---

## End-to-End Example

```python
@codec
class PatientFeedbackCodec(DjangoBaseCodec):
    def persist(self, *, response, parsed) -> dict:
        from django.db import transaction
        from chatlab.models import Feedback, FeedbackMetric

        with transaction.atomic():
            fb = Feedback.objects.create(
                simulation=response.simulation,
                summary=parsed.summary,
                identity=response.identity_str,
            )
            FeedbackMetric.objects.bulk_create([
                FeedbackMetric(feedback=fb, name=m.key, value=m.value)
                for m in parsed.metrics
            ])

        return {"feedback_id": fb.id, "metric_count": len(parsed.metrics)}
```

---

## Testing Persistence

```python
def test_feedback_codec_persist(db, simulation):
    from chatlab.ai.codecs import PatientFeedbackCodec as Codec
    from chatlab.models import Feedback

    codec = Codec()

    parsed = type("Parsed", (), {
        "summary": "Great job",
        "metrics": [type("M", (), {"key": "accuracy", "value": 0.9})()],
        "model_dump": lambda self=None: {"summary": "Great job", "metrics": [{"key": "accuracy", "value": 0.9}]},
    })()

    resp = type("Resp", (), {
        "simulation": simulation,
        "identity_str": "chatlab.standardized_patient.feedback",
        "request_correlation_id": "abc-123",
        "namespace": "chatlab", "kind": "standardized_patient", "name": "feedback",
    })()

    result = codec.persist(response=resp, parsed=parsed)
    assert "feedback_id" in result
    assert Feedback.objects.filter(id=result["feedback_id"]).exists()
```

---

## Summary

- **Codecs** are the place to persist validated AI outputs into your DB  
- Use **atomic** transactions, **bulk_create**, and **correlation_id** for robustness  
- Keep return values **small** and serializable  
- Rely on **identity alignment** for auto-wiring with Services & Schemas

---

© 2025 Jackfruit SimWorks • simcore_ai_django
