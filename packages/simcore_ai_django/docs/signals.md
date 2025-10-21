# Signals & Emitters — simcore_ai_django

> Observe AI requests and responses with Django-friendly signals.

---

## Overview

`simcore_ai_django` ships with a **signal-based emitter** so your app can observe and react to AI activity (requests, responses, failures, streaming) without tightly coupling business logic to the service layer.

The default emitter instance lives at `simcore_ai_django.signals.emitter` and is wired automatically by `DjangoBaseLLMService`.

---

## Signal Emitter

```python
from simcore_ai_django.signals import emitter  # DjangoSignalEmitter
```

The emitter exposes methods mirroring signal names:

| Method | Signal | Description |
|--------|--------|-------------|
| `request_sent(payload)` | `ai_request_sent` | Fired before an LLM request is dispatched. |
| `response_received(payload)` | `ai_response_received` | Fired when a provider response arrives. |
| `response_ready(payload)` | `ai_response_ready` | Fired after codec validation/persistence succeeds. |
| `response_failed(payload)` | `ai_response_failed` | Fired when request or codec processing fails. |
| `outbox_dispatch(payload)` | `ai_outbox_dispatch` | Fired when an outbox event is emitted. |

Payloads are `TypedDict`s defined in `simcore_ai_django.signals`.

---

## Payload Shape

Example payload for `ai_request_sent`:

```python
{
  "request": {...},           # serialized request DTO
  "simulation_pk": 42,
  "origin": "chatlab",
  "bucket": "standardized_patient",
  "service_name": "initial",
  "codec_name": "standardized_patient.initial",
  "correlation_id": UUID(...),
}
```

`response_received` and `response_ready` include `response` dictionaries with provider metadata, usage stats, and persisted identifiers. `response_failed` contains an `error` string and correlation details.

---

## Connecting Receivers

Register receivers in `apps.py.ready()` or another import-on-startup module:

```python
# myapp/ai/signals.py
from django.dispatch import receiver
from simcore_ai_django.signals import (
    ai_request_sent,
    ai_response_received,
    ai_response_ready,
    ai_response_failed,
)

@receiver(ai_request_sent)
def on_ai_request(sender, **payload):
    print("AI request", payload.get("origin"), payload.get("request"))

@receiver(ai_response_ready)
def on_ai_response_ready(sender, **payload):
    print("AI response ready", payload.get("response"))
```

Wire the module in your app config:

```python
class MyAppConfig(AppConfig):
    name = "myapp"
    def ready(self):
        import myapp.ai.signals  # noqa: F401
```

Signals are sent with `send_robust`, so receiver exceptions are isolated and logged.

---

## Correlation IDs & Ordering

- Every request carries a **correlation_id** (UUID) stored on request/response payloads.
- Streaming flows emit `ai_response_received` chunks followed by `ai_response_ready` when final persistence completes.
- Use the correlation ID to tie together request, streaming chunks, and final persistence events.

---

## Custom Emitters

You can override the emitter on a per-service basis:

```python
class MyService(DjangoBaseLLMService):
    emitter = MyCustomEmitter()
```

Custom emitters should implement the same methods as `DjangoSignalEmitter` (`request_sent`, `response_received`, etc.).

---

## Summary

- Five Django signals expose the full service lifecycle.
- Payloads are structured dictionaries (TypedDict contracts) for type safety.
- Replace the emitter to integrate with websockets, message buses, or other systems.

---

© 2025 Jackfruit SimWorks • simcore_ai_django
