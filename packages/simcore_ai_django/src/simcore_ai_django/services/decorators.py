"""Django-aware @llm_service decorator that auto-derives (origin, bucket, name),
enforces dot-only identity semantics, and applies collision policy."""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Type, overload, cast, Any

from simcore_ai.tracing import service_span_sync
from .base import DjangoBaseLLMService, DjangoExecutableLLMService
from simcore_ai_django.identity import derive_django_identity_for_class, resolve_collision_django

try:
    from simcore_ai.services.registry import ServicesRegistry
except ImportError:
    ServicesRegistry = None


__all__ = ["llm_service"]


@overload
def llm_service(_func: None = None, *, origin: Optional[str] = ..., bucket: Optional[str] = ..., name: Optional[str] = ..., codec: Optional[str] = ..., prompt_plan: Optional[Sequence[tuple[str, str]]] = ...) -> Callable[[Callable[..., Any]], type]: ...
@overload
def llm_service(_func: Callable[..., Any], *, origin: Optional[str] = ..., bucket: Optional[str] = ..., name: Optional[str] = ..., codec: Optional[str] = ..., prompt_plan: Optional[Sequence[tuple[str, str]]] = ...) -> type: ...

def llm_service(
    _func: Optional[Callable[..., Any]] = None,
    *,
    origin: Optional[str] = None,
    bucket: Optional[str] = None,
    name: Optional[str] = None,
    codec: Optional[str] = None,
    prompt_plan: Optional[Sequence[tuple[str, str]]] = None,
):
    """
    Django-aware LLM service decorator usable as either:

        @llm_service
        async def generate(simulation, slim): ...

    or:

        @llm_service(origin="chatlab", bucket="patient", codec="default", prompt_plan=(("initial","hotwash"),))
        async def generate(simulation, slim): ...

    In bare form, identity is auto-derived from the generated class using
    `derive_django_identity_for_class`. In called form, any provided identity
    fields override derivation and still pass through collision resolution.
    """

    def _apply(func: Callable[..., Any]) -> type:
        base_cls: Type[DjangoExecutableLLMService | DjangoBaseLLMService]
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
        _FnService.codec_name = (codec or "default")
        _FnService.prompt_plan = tuple(prompt_plan) if prompt_plan is not None else tuple()

        return _FnService

    # Bare form: @llm_service
    if _func is not None:
        if not callable(_func):
            raise TypeError("llm_service: decorated object must be callable")
        return _apply(cast(Callable[..., Any], _func))

    # Called form: @llm_service(...)
    return _apply