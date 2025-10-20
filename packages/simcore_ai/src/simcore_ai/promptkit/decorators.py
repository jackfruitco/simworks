# simcore_ai/promptkit/decorators.py
"""Core (non-Django) decorators for PromptKit built on the base decorator factory.

This module defines the **core** PromptKit decorator using the shared dual-form
factory and the **default module-centric identity resolver**. It intentionally
remains framework-agnostic and does not import any Django modules.

Usage (dual-form):

    from simcore_ai.promptkit.decorators import prompt_section

    @prompt_section
    class PatientIntro(PromptSection):
        instruction = "Gather patient demographics."

    @prompt_section(origin="chatlab", bucket="patient", name="intro")
    class PatientIntroExplicit(PromptSection):
        instruction = "Gather patient demographics."

The identity parts are resolved with the following defaults in core:
- origin: module root or "simcore"
- bucket: second module segment or "default"
- name:   snake_case(class name with common suffixes removed)

Registration is performed via `PromptRegistry.register(cls)`. The decorator is
safe to import even when registries are unavailable at import time.
"""
from __future__ import annotations

import logging

from simcore_ai.decorators.base import (
    make_class_decorator,
    default_identity_resolver,
)
from .registry import PromptRegistry
from .types import PromptSection

logger = logging.getLogger(__name__)

# Build the dual-form decorator using the shared factory and core resolver.
# Registration is passed as a post hook and is guarded internally by the factory.
prompt_section = make_class_decorator(
    identity_resolver=default_identity_resolver,
    post_register=PromptRegistry.register,
)

__all__ = ["prompt_section", "PromptSection"]
