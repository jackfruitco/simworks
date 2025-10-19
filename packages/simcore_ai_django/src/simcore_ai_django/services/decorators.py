"""Django-aware @llm_service decorator that auto-derives (origin, bucket, name),
enforces dot-only identity semantics, and applies collision policy."""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Type

from simcore_ai.tracing import service_span_sync

from .base import DjangoBaseLLMService, DjangoExecutableLLMService
from simcore_ai_django.identity import derive_django_identity_for_class, resolve_collision_django

try:
    from simcore_ai.services.registry import ServicesRegistry
except ImportError:
    ServicesRegistry = None


__all__ = ["llm_service"]


def llm_service(
    *,
    origin: Optional[str] = None,
    bucket: Optional[str] = None,
    name: Optional[str] = None,
    codec: Optional[str] = None,
    prompt_plan: Optional[Sequence[tuple[str, str]]] = None,
):
    """
    Decorator to define a Django-aware LLM service wrapping a function.

    This decorator auto-derives the service's identity based on the decorated function's class,
    aligning with the new identity system. The canonical identity is formed as a dot-only string
    in the form 'origin.bucket.name', where each component is normalized to snake_case.

    Parameters:
        origin (Optional[str]): Optional origin string for the service identity.
        bucket (Optional[str]): Optional bucket string for the service identity.
        name (Optional[str]): Optional name string for the service identity.
        codec (Optional[str]): Codec name used by the service; defaults to "default".
        prompt_plan (Optional[Sequence[tuple[str, str]]]): Optional prompting plan as a sequence of (role, content) tuples.

    The identity arguments are all optional; if omitted, the identity is derived automatically from the function's class.

    Usage:

        @llm_service(name="my_service")
        async def my_function(simulation, slim):
            ...

    The wrapped function can accept either one argument (simulation) or two arguments (simulation, slim).

    Returns:
        A Django LLM service class wrapping the decorated function.
    """
    resolved_codec = codec or "default"
    resolved_plan = tuple(prompt_plan) if prompt_plan is not None else tuple()

    def wrap(func: Callable):
        base_cls: Type[DjangoExecutableLLMService | DjangoBaseLLMService]
        # Prefer DjangoExecutableLLMService if available
        base_cls = DjangoExecutableLLMService if hasattr(DjangoExecutableLLMService, "on_success") else DjangoBaseLLMService

        class _FnService(base_cls):
            """Auto-generated Django LLM service wrapper for a function."""

            async def on_success(self, simulation, slim):
                import inspect

                sig = inspect.signature(func)
                if len(sig.parameters) >= 2:
                    return await func(simulation, slim)
                elif len(sig.parameters) == 1:
                    return await func(simulation)
                else:
                    return None

        _FnService.__name__ = f"{func.__name__}_Service"
        _FnService.__module__ = getattr(func, "__module__", __name__)

        with service_span_sync("llm_service.derive_identity", attributes={"func": func.__name__}):
            org, buck, nm = derive_django_identity_for_class(_FnService, origin=origin, bucket=bucket, name=name)

            def _exists(t: tuple[str, str, str]) -> bool:
                if ServicesRegistry is not None:
                    return ServicesRegistry.has(*t)
                return False

            org, buck, nm = resolve_collision_django("service", (org, buck, nm), exists=_exists)

        _FnService.origin = org
        _FnService.bucket = buck
        _FnService.name = nm
        _FnService.codec_name = resolved_codec
        _FnService.prompt_plan = resolved_plan

        return _FnService

    return wrap
