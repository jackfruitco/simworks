from __future__ import annotations

"""
Decorator for defining lightweight LLM services.

This decorator generates a `BaseLLMService` subclass from a simple async
function. It enforces the v3 identity model (origin/bucket/name) and does
**not** accept the legacy `namespace` argument (will fail hard if used).

Usage:
    @llm_service(origin="chatlab", bucket="patient")
    async def generate(simulation, slim):
        ...

Notes:
- `origin` and `bucket` are required (keyword-only).
- `name` defaults to the wrapped function's name when omitted.
- `codec` defaults to "default" when omitted.
- `prompt_plan` defaults to an empty tuple.
"""

from typing import Sequence, Callable, Optional
from .base import BaseLLMService


def llm_service(
    *,
    origin: str,
    bucket: str,
    name: Optional[str] = None,
    codec: Optional[str] = None,
    prompt_plan: Optional[Sequence[tuple[str, str]]] = None,
):
    """
    Decorate a simple async function and expose it as a `BaseLLMService` subclass.

    Required:
        origin: Producer/project (e.g., "simcore", "trainerlab", "chatlab").
        bucket: Functional group (e.g., "feedback", "triage", "patient").

    Optional:
        name:        Concrete operation; defaults to the function name.
        codec:       Name of a registered codec; defaults to "default".
        prompt_plan: Sequence of (section_name, section_key); defaults to empty.

    Returns:
        A subclass of `BaseLLMService` that delegates to the wrapped function's
        body in `on_success`.
    """
    # Fail fast on missing required identity parts
    if not origin or not isinstance(origin, str):
        raise TypeError("llm_service: 'origin' must be a non-empty string")
    if not bucket or not isinstance(bucket, str):
        raise TypeError("llm_service: 'bucket' must be a non-empty string")

    resolved_codec = codec or "default"
    resolved_plan = tuple(prompt_plan) if prompt_plan is not None else tuple()

    def wrap(func: Callable):
        svc_name = name or func.__name__

        class _FnServiceLLMService(BaseLLMService):
            """Auto-generated service wrapper for function-level LLM services."""

            async def on_success(self, simulation, slim):
                # If the function expects (simulation, slim), pass both; else do nothing.
                if getattr(func, "__call__", None) and getattr(func, "__code__", None):
                    if func.__code__.co_argcount >= 2:
                        return await func(simulation, slim)
                return None

        # Bind class-level identity/config from decorator args (closure-safe)
        _FnServiceLLMService.origin = origin
        _FnServiceLLMService.bucket = bucket
        _FnServiceLLMService.name = svc_name
        _FnServiceLLMService.codec_name = resolved_codec
        _FnServiceLLMService.prompt_plan = resolved_plan
        _FnServiceLLMService.__name__ = f"{func.__name__}_Service"
        _FnServiceLLMService.__module__ = getattr(func, "__module__", __name__)
        return _FnServiceLLMService

    return wrap