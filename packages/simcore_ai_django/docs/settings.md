# Settings & Environment Variables — simcore_ai_django

> Reference guide for environment variables and Django settings that influence AI service behavior.

---

## Overview

`simcore_ai_django` integrates deeply with Django’s settings and your environment.
This document explains the configuration hierarchy, key environment variables,
and safe defaults used by the AI framework.

---

## Configuration Hierarchy

The framework checks configuration in this order (highest → lowest precedence):

1. **Django `settings.py`**
2. **Environment variables**
3. **Built‑in defaults**

Example:
```python
from django.conf import settings
DEBUG = getattr(settings, "SIMCORE_AI_DEBUG", os.getenv("SIMCORE_AI_DEBUG", False))
```

---

## Environment Variables

### Core Variables

| Variable | Type | Default | Description |
|:--|:--|:--|:--|
| `SIMCORE_AI_DEBUG` | `bool` | `False` | Enables verbose logging and registry collision tracing |
| `SIMCORE_AI_BACKEND` | `str` | `"immediate"` | Execution backend (`immediate`, `celery`, etc.) |
| `AI_IDENTITY_STRIP_TOKENS` | `str (CSV)` | `""` | Adds custom tokens to strip from identity class names |
| `SIMCORE_AI_PROVIDER` | `str` | `"openai"` | Default AI provider |
| `SIMCORE_AI_TIMEOUT` | `int` | `60` | Request timeout (seconds) |
| `SIMCORE_AI_API_KEY` | `str` | `None` | API key if provider not using Django secrets |

---

## Django Settings (Optional Overrides)

| Setting | Description |
|:--|:--|
| `SIMCORE_AI_DEBUG` | Overrides `SIMCORE_AI_DEBUG` env var. Enables full trace mode. |
| `AI_IDENTITY_STRIP_TOKENS` | List or CSV string of additional tokens to remove when deriving identity. |
| `SIMCORE_AI_BACKEND` | Execution backend selection. `"immediate"` (default) or `"celery"`. |
| `SIMCORE_AI_PROVIDER` | Name of provider; should match installed provider class name. |
| `SIMCORE_AI_TIMEOUT` | Global default request timeout for LLM calls. |
| `SIMCORE_AI_API_KEY` | Secret key for provider if not stored in system envs. |

---

## Identity Token Configuration

### Base Tokens (Core)

```
DEFAULT_STRIP_TOKENS = {
    "Codec", "Service", "Prompt", "PromptSection",
    "Section", "Response", "Generate", "Output", "Schema",
}
```

### Django Extensions

Django automatically extends these with:
- All app names (`app`, `App`, `AppName`)
- Tokens from `AI_IDENTITY_STRIP_TOKENS` (env or settings)
- Tokens from `AppConfig.identity_strip_tokens` (per app)

### Example

```python
# settings.py
AI_IDENTITY_STRIP_TOKENS = ["Patient", "Generate", "Output"]
```

```python
# apps.py
class ChatlabConfig(AppConfig):
    identity_strip_tokens = {"Chatlab", "Generate"}
```

Result → tokens `{"Chatlab", "Generate", "Patient"}` are removed from edges.

---

## Backend Configuration

### Immediate Backend (Default)
Runs tasks synchronously in the request thread.
Useful for development or small workloads.

### Celery Backend
If Celery workers are configured, `.using("celery")` can enqueue tasks:

```python
MyService.using("celery").enqueue(simulation=my_sim)
```

Celery connection settings:
```python
CELERY_BROKER_URL = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = "redis://localhost:6379/0"
```

---

## Debug Mode

When `SIMCORE_AI_DEBUG` or `settings.SIMCORE_AI_DEBUG` is true:
- Registry collisions raise exceptions (instead of silent renaming)
- LLM payloads are logged (without secrets)
- Prompt render times are measured
- Provider round‑trip timings are printed

---

## Safety Notes

✅ **Always** store provider API keys in `.env` or Django Secrets Manager.  
🚫 Never commit `SIMCORE_AI_API_KEY` to source control.  
⚙️ Keep `SIMCORE_AI_DEBUG=False` in production.

---

## Quick Diagnostic

```bash
python manage.py shell_plus
>>> from simcore_ai.identity.utils import dump_identity_config
>>> dump_identity_config()
{
  "DEBUG": True,
  "STRIP_TOKENS": ["Codec", "Service", "Prompt", "Patient", ...],
  "BACKEND": "immediate"
}
```

---

## Summary

- Environment variables control default AI runtime behavior.
- Django settings override envs when defined.
- Identity and registry behaviors are fully configurable.
- Debug mode offers extra safety and insight during development.

---

© 2025 Jackfruit SimWorks • simcore_ai_django
