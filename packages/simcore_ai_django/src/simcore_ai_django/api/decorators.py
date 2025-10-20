# simcore_ai_django/api/decorators.py
"""Django-aware decorator re-exports for the public SimWorks API.

This module re-exports the **Django-layer** decorators so app code can import
from a single, stable location. These decorators are dual-form (`@dec` or
`@dec(...)`) and use the Django-aware identity resolver (leaf-class based,
app/settings token stripping), with guarded registration/collision handling.

Exports:
    - codec          — Register a Django codec class (tuple³ identity).
    - llm_service    — Wrap an async function as a Django service class.
    - prompt_section — Register a PromptSection subclass.
    - prompt_scenario — (stub) Scenario-level prompt decorator.
"""
from __future__ import annotations

from simcore_ai_django.services.decorators import llm_service

from simcore_ai_django.codecs.decorators import codec
from simcore_ai_django.promptkit.decorators import prompt_section, prompt_scenario

__all__ = [
    "codec",
    "llm_service",
    "prompt_section",
    "prompt_scenario",
]
