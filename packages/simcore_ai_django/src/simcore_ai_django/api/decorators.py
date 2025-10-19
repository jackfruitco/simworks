# simcore_ai_django/api/decorators.py
"""Provides decorators for use within the simcore_ai_django API.

This module imports and re-exports several decorators from the `simcore_ai` library
to simplify access and ensure consistent usage. The included decorators pertain to
codecs, large language model (LLM) services, prompts management, and related
functional areas.

Decorators:
    - `codec`: Handles encoding/decoding operations.
    - `llm_service`: Enables integration of large language model services.
    - `prompt_section`: Manages sections within prompt definitions.
    - `prompt_scenario`: Manages scenarios within prompt definitions.

Exports:
    - codec
    - llm_service
    - prompt_section
    - prompt_scenario
"""
from __future__ import annotations

from simcore_ai.services.decorators import llm_service

from simcore_ai_django.codecs.decorators import codec
from simcore_ai_django.promptkit.decorators import prompt_section, prompt_scenario

__all__ = [
    "codec",
    "llm_service",
    "prompt_section",
    "prompt_scenario",
]
