# Signals & Emitters — simcore_ai_django

> Observe AI requests and responses with Django-friendly signals.

---

## Overview

`simcore_ai_django` ships with a **signal-based emitter** so your app can observe
and react to AI activity (requests, streaming chunks, failures) without tightly
coupling business logic to the service layer.

This is ideal for:
- Auditing and telemetry
- Persisting request/response metadata
- Realtime UI updates (websockets, SSE)
- Side effects (notifications, counters, etc.)

---

## Signal Emitter

A default emitter instance is provided and used by `DjangoBaseService`:

```python
from simcore_ai_django.signals import emitter  # DjangoSignalEmitter
```

Services set this automatically unless overridden:
```python
class MyService(DjangoBaseService):
    pass  # self.emitter is set to the default DjangoSignalEmitter
```

---

## Emitted Events

### 1) `emit_request(simulation_id, identity, request_dto)`

**When:** Just before sending the LLM request.  
**Payload:**

```python
{
  "simulation_id": int,
  "identity": "namespace.kind.name",
  "request": {
    "correlation_id": "uuid4",
    "namespace": "namespace",
    "kind": "kind",
    "name": "name",
    "codec": "namespace.kind.codec_name",
    "messages": [ { "role": "developer", "content": [...] }, ... ],
    "output_schema": {...} | None,
    "output_schema_cls": "Qualified.Class.Name" | None,
    "meta": {...}
  }
}
```

Useful for logging, auditing, and correlating with subsequent events.

---

### 2) `emit_response(simulation_id, identity, response_dto)`

**When:** After a successful non-streaming completion.  
**Payload:**

```python
{
  "simulation_id": int,
  "identity": "namespace.kind.name",
  "response": {
    "request_correlation_id": "uuid4",
    "codec": "namespace.kind.codec_name",
    "namespace": "namespace",
    "kind": "kind",
    "name": "name",
    "content": [...],
    "usage": {...} | None,
    "provider": "openai" | "anthropic" | ...,
    "metadata": {...}
  }
}
```

Use this to persist final AI output, run post-processing, or update UI.

---

### 3) `emit_failure(simulation_id, identity, correlation_id, error)`

**When:** After an exception (request/stream).  
**Payload:**

```python
{
  "simulation_id": int,
  "identity": "namespace.kind.name",
  "correlation_id": "uuid4",
  "error": "trace or message"
}
```

Best used to capture errors, retry counts, and notify monitoring systems.

---

### 4) `emit_stream_chunk(simulation_id, identity, chunk_dto)`

**When:** During streaming responses (tokens/segments).  
**Payload:**

```python
{
  "simulation_id": int,
  "identity": "namespace.kind.name",
  "chunk": {
    "request_correlation_id": "uuid4",
    "delta": "text or structured piece",
    "index": 42,     # optional order
    "done": False    # if the provider marks a final partial
  }
}
```

You can broadcast these events over websockets to update the UI in real-time.

---

### 5) `emit_stream_complete(simulation_id, identity, correlation_id)`

**When:** After a stream ends gracefully.  
**Payload:**

```python
{
  "simulation_id": int,
  "identity": "namespace.kind.name",
  "correlation_id": "uuid4"
}
```

Use this to close UI streams or finalize partial persistence.

---

## Connecting Receivers

Add receivers in any `apps.py` `ready()` or module import path:

```python
# myapp/ai/signals.py
from django.dispatch import receiver
from simcore_ai_django.signals import (
    request_signal,
    response_signal,
    failure_signal,
    stream_chunk_signal,
    stream_complete_signal,
)

@receiver(request_signal)
def on_ai_request(sender, **payload):
    # sender is the service class
    print("AI request:", payload["identity"], payload.get("request"))

@receiver(response_signal)
def on_ai_response(sender, **payload):
    print("AI response:", payload["identity"], payload.get("response"))

@receiver(failure_signal)
def on_ai_failure(sender, **payload):
    print("AI failure:", payload["identity"], payload.get("error"))

@receiver(stream_chunk_signal)
def on_ai_stream_chunk(sender, **payload):
    print("AI chunk:", payload["identity"], payload.get("chunk"))

@receiver(stream_complete_signal)
def on_ai_stream_complete(sender, **payload):
    print("AI stream complete:", payload["identity"], payload.get("correlation_id"))
```

Wire them up in `apps.py`:

```python
class MyAppConfig(AppConfig):
    name = "myapp"
    def ready(self):
        import myapp.ai.signals  # noqa: F401
```

---

## Correlation IDs & Ordering

- Every request has a **correlation_id** (UUID)
- The same ID is propagated into responses and stream chunks
- For streaming, your receiver may add an **index** if the provider does not supply ordering

This makes it safe to join chunks and completions later.

---

## Idempotency & Retries

Your receivers might be called more than once in error scenarios.  
Use `request_correlation_id` + identity to dedupe persisted records.

Example pattern:

```python
# Guard by correlation_id
AIResponse.objects.get_or_create(
    correlation_id=payload["response"]["request_correlation_id"],
    defaults={...},
)
```

---

## Security Tips

- Avoid logging **full** prompts or responses in production.
- Scrub PII before persistence.
- Use settings to disable streaming when necessary for sensitive domains.

---

## Troubleshooting

- Signals not firing? Ensure the module that registers receivers is **imported** on startup (`apps.py:ready()`).
- Missing identity fields? Confirm your classes derive identity via mixins or class attributes.
- Out-of-order chunks? Buffer by `request_correlation_id` and index before assembling.

---

## Summary

✅ Observe every step of the AI request lifecycle  
✅ Integrates with Django signals seamlessly  
✅ Correlate requests, streams, responses, and failures  
✅ Ideal for telemetry, persistence, and realtime UX

---

© 2025 Jackfruit SimWorks • simcore_ai_django
