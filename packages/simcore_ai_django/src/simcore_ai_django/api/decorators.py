# simcore_ai_django/api/decorators.py
"""Django-aware decorator re-exports for public consumption.

This module re-exports the **Django-layer** decorator instances so app code can
import them from a single, stable location:

    from simcore_ai_django.api.decorators import llm_service, codec, prompt_section, response_schema

All decorators are dual-form (`@dec` or `@dec(...)`) and use the Django-aware
identity resolver and token stripping via mixins. Registration enforces tuple³
uniqueness; collisions are handled by the decorators with hyphen-int suffixing
on the **name** and WARNING logs.

Exports:
    - llm_service     — Wrap an async function or register a service class.
    - codec           — Register a codec class.
    - prompt_section  — Register a PromptSection subclass.
    - response_schema — Register a response schema class.
"""
from __future__ import annotations

from simcore_ai_django.codecs.decorators import codec
from simcore_ai_django.promptkit.decorators import prompt_section
from simcore_ai_django.schemas.decorators import response_schema
from simcore_ai_django.services.decorators import llm_service

__all__ = [
    "llm_service",
    "codec",
    "prompt_section",
    "response_schema",
]
