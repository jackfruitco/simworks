# Settings & Environment Variables — simcore_ai_django

> Reference guide for configuration knobs that influence AI service behavior.

---

## Overview

`simcore_ai_django` leans on Django settings for configuration. Environment variables are minimal; most options live under structured settings so they can be overridden per environment.

Configuration precedence:

1. **Service overrides** (class attributes or `.using(...)` calls)
2. **Django settings**
3. **Built-in defaults**

---

## Django Settings

### Identity Tokens

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `SIMCORE_AI_IDENTITY_STRIP_TOKENS` | list[str] | `[]` | Global extra tokens stripped from identity names (merged with app tokens). |
| `AI_IDENTITY_STRIP_TOKENS` | list[str] | `[]` | Legacy alias consumed by identity utils. |

Each app may also define `identity_strip_tokens` **or** `AI_IDENTITY_STRIP_TOKENS` on its `AppConfig`. Both forms are honored.

### Codec Registration

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `SIMCORE_AI_VALIDATE_CODECS_ON_REGISTER` | bool | `False` | When true, codec registration instantiates the class once to surface import-time errors. |

### Execution Backends

`AI_EXECUTION_BACKENDS` is a dictionary that configures dispatch defaults and backend metadata:

```python
AI_EXECUTION_BACKENDS = {
    "DEFAULT_MODE": "sync",      # or "async"
    "DEFAULT_BACKEND": "immediate",  # or "celery"
    "CELERY": {
        "queue_default": "ai-default",
    },
}
```

- `DEFAULT_MODE` → fallback for `execution_mode` when not set on a service.
- `DEFAULT_BACKEND` → fallback for `execution_backend`.
- `CELERY.queue_default` → optional queue name used by the Celery backend.

### Prompt/Tracing Utilities

The prompt engine and service base classes emit OpenTelemetry spans automatically. No extra settings are required, but you can configure OpenTelemetry exporters as usual in Django settings.

---

## Environment Variables

While most configuration lives in Django settings, a few environment variables are commonly used alongside this package:

| Variable | Purpose |
|----------|---------|
| `SIMCORE_AI_IDENTITY_STRIP_TOKENS` | CSV string parsed into the setting of the same name (useful for twelve-factor deployments). |
| Provider-specific keys (e.g., `OPENAI_API_KEY`) | Consumed by your chosen `simcore_ai` provider implementation. |

Everything else—including execution mode, codecs, registries, and signals—is controlled via Django settings or service-level overrides.

---

## Inspecting Configuration

Quick helpers you can run from `manage.py shell`:

```python
from simcore_ai_django.execution.helpers import get_settings_dict
print(get_settings_dict())  # AI_EXECUTION_BACKENDS snapshot

from simcore_ai_django.identity import derive_django_identity_for_class
from myapp.ai.prompts.sections import PatientInitialSection
print(derive_django_identity_for_class(PatientInitialSection))
```

---

## Summary

- Prefer structured Django settings over ad-hoc environment variables.
- Use `AI_EXECUTION_BACKENDS` to control default mode/backend/queue.
- Identity stripping tokens can be declared globally or per-app.
- Enable `SIMCORE_AI_VALIDATE_CODECS_ON_REGISTER` to surface codec errors early.

---

© 2025 Jackfruit SimWorks • simcore_ai_django
