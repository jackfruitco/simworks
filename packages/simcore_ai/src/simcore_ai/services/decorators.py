# simcore_ai/services/decorators.py
"""Core (non-Django) LLM service decorator built on the base decorator factory.

This module defines the **core** `llm_service` decorator using the shared
dual-form factory and the **default module-centric identity resolver**. It
remains framework-agnostic and does not import any Django modules.

Usage (dual-form):

    from simcore_ai.services.decorators import llm_service

    @llm_service
    async def generate(simulation, slim):
        ...

    @llm_service(origin="chatlab", bucket="patient", name="initial", codec="default")
    async def generate_initial(simulation, slim):
        ...

Identity defaults in core:
- origin: module root or "simcore"
- bucket: second module segment or "default"
- name:   snake_case(function/class name with common suffixes removed)

The decorator wraps an async function in a `BaseLLMService` subclass and binds
`origin`, `bucket`, `name`, `codec_name` (default "default"), and `prompt_plan`.
"""
from __future__ import annotations

from simcore_ai.decorators.base import (
    make_fn_service_decorator,
    default_identity_resolver,
)

# Build the dual-form function→service decorator using the shared factory.
llm_service = make_fn_service_decorator(
    identity_resolver=default_identity_resolver,
)

__all__ = ["llm_service"]
