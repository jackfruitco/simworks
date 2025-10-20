# simcore_ai/decorators/base.py
from __future__ import annotations

"""
Base decorator factory utilities for SimCore AI.

This module centralizes dual-form decorator behavior and identity derivation,
so domain-specific decorators (prompts, services, codecs, etc.) can share a
single, pluggable implementation while choosing their own identity resolver.

Key ideas:
- Dual-form decorators: usable as `@dec` or `@dec(origin=..., bucket=..., name=...)`.
- Pluggable identity resolvers: core keeps a pure, module-centric resolver;
  Django layer can override with an app-aware resolver without duplicating logic.
- Optional post-register hooks: let each domain handle registry/collision policy
  without coupling this base module to any registry implementation.

This file must not import from any Django-specific modules.
"""

import inspect
from typing import Any, Callable, Optional, Protocol, Sequence, Type, TypeVar, overload, cast

from simcore_ai.identity.utils import snake  # reuse project-standard snake_case

# ---------- Types & Protocols ----------

T = TypeVar("T", bound=Type[Any])

class IdentityResolver(Protocol):
    def __call__(
        self,
        obj: Any,
        *,
        origin: Optional[str],
        bucket: Optional[str],
        name: Optional[str],
    ) -> tuple[str, str, str]: ...


# ---------- Helpers ----------

_CORE_AFFIX_STRIP: tuple[str, ...] = (
    "Prompt",
    "Section",
    "Service",
    "Codec",
    "Generate",
    "Response",
    "Mixin",
)

def _strip_affixes(name: str, tokens: Sequence[str]) -> str:
    """
    Remove any of the given tokens from the start or end of `name`,
    repeating until no further change occurs. This ensures we handle
    stacked affixes like 'PatientInitialPrompt' -> 'Initial' and
    'JsonCodec' -> 'Json'.
    """
    changed = True
    while changed:
        changed = False
        for tok in tokens:
            if name.startswith(tok) and len(name) > len(tok):
                name = name[len(tok):]
                changed = True
            if name.endswith(tok) and len(name) > len(tok):
                name = name[:-len(tok)]
                changed = True
    return name

def _derive_from_module(obj: Any) -> tuple[str, str, str]:
    """
    Best-effort extraction of (origin, bucket, name) parts from module/name.
    - origin: first module segment or 'simcore'
    - bucket: second module segment or 'default'
    - name:   object __name__ (un-snake-cased; caller should snake-case)
    """
    mod = getattr(obj, "__module__", "") or ""
    parts = [p for p in mod.split(".") if p]
    origin = parts[0] if parts else "simcore"
    bucket = parts[1] if len(parts) > 1 else "default"
    name = getattr(obj, "__name__", None) or "default"
    return origin, bucket, name


# ---------- Default (core) identity resolver ----------

def default_identity_resolver(
    obj: Any,
    *,
    origin: Optional[str],
    bucket: Optional[str],
    name: Optional[str],
) -> tuple[str, str, str]:
    """
    Pure, module-centric identity resolver for core usage.

    Resolution precedence (each part independently):
      explicit override -> module-derived default

    Defaults:
      origin: module root or 'simcore'
      bucket: second module segment or 'default'
      name:   snake_case(class/function name with common affixes removed)

    All returned parts are snake-cased.
    """
    mod_origin, mod_bucket, mod_name = _derive_from_module(obj)

    raw_origin = origin or mod_origin or "simcore_ai"
    raw_bucket = bucket or mod_bucket or "default"
    raw_name = name or _strip_affixes(mod_name, _CORE_AFFIX_STRIP) or "default"

    return snake(raw_origin), snake(raw_bucket), snake(raw_name)


# ---------- Decorator factories ---------------------------------------------
# Decorator factories are used to create dual-form decorators.
# ----------------------------------------------------------------------------
@overload
def make_class_decorator(
    identity_resolver: IdentityResolver,
    *,
    post_register: Optional[Callable[[Type[Any]], None]] = ...,
    bind_extras: Optional[Callable[[Type[Any], dict[str, Any]], None]] = ...,
) -> Callable[[Optional[T],], T] | Callable[..., Callable[[T], T]]: ...
@overload
def make_class_decorator(
    identity_resolver: IdentityResolver,
    *,
    post_register: Optional[Callable[[Type[Any]], None]] = ...,
    bind_extras: Optional[Callable[[Type[Any], dict[str, Any]], None]] = ...,
) -> Callable[[Optional[T],], T] | Callable[..., Callable[[T], T]]: ...
def make_class_decorator(
    identity_resolver: IdentityResolver,
    *,
    post_register: Optional[Callable[[Type[Any]], None]] = None,
    bind_extras: Optional[Callable[[Type[Any], dict[str, Any]], None]] = None,
):
    """
    Return a dual-form class decorator builder using the provided identity resolver.

    Usage:
        prompt_section = make_class_decorator(default_identity_resolver, post_register=PromptRegistry.register)

        @prompt_section
        class MyPrompt(...): ...

        @prompt_section(origin="chatlab", bucket="default", name="patient_initial")
        class MyPrompt(...): ...
    """
    def decorator(
        _cls: Optional[T] = None,
        *,
        origin: Optional[str] = None,
        bucket: Optional[str] = None,
        name: Optional[str] = None,
        **extras: Any,
    ):
        def _apply(cls: T) -> T:
            o, b, n = identity_resolver(cls, origin=origin, bucket=bucket, name=name)
            setattr(cls, "origin", o)
            setattr(cls, "bucket", b)
            setattr(cls, "name", n)

            if bind_extras is not None:
                try:
                    bind_extras(cls, extras)
                except Exception:
                    # Extras binding must never prevent class registration
                    pass

            if post_register is not None:
                try:
                    post_register(cls)
                except Exception:
                    # Registries may be optional or unavailable at import time
                    pass
            return cls

        if _cls is not None:
            return _apply(cast(T, _cls))
        return _apply
    return decorator


@overload
def make_fn_service_decorator(
    identity_resolver: IdentityResolver,
    *,
    post_register: Optional[Callable[[Type[Any]], None]] = ...,
    bind_extras: Optional[Callable[[Type[Any], dict[str, Any]], None]] = ...,
) -> Callable[..., Type[Any]]: ...
@overload
def make_fn_service_decorator(
    identity_resolver: IdentityResolver,
    *,
    post_register: Optional[Callable[[Type[Any]], None]] = ...,
    bind_extras: Optional[Callable[[Type[Any], dict[str, Any]], None]] = ...,
) -> Callable[..., Type[Any]]: ...
def make_fn_service_decorator(
    identity_resolver: IdentityResolver,
    *,
    post_register: Optional[Callable[[Type[Any]], None]] = None,
    bind_extras: Optional[Callable[[Type[Any], dict[str, Any]], None]] = None,
):
    """
    Return a dual-form decorator that turns an async function into a BaseLLMService subclass.

    The identity is resolved against the **generated class**, not the function, so that
    suffix stripping like 'Service' applies consistently in both core and Django layers.
    """
    # Import here to avoid import cycles on module import
    from simcore_ai.services import BaseLLMService  # local import by design

    def llm_service(
        _func: Optional[Callable[..., Any]] = None,
        *,
        origin: Optional[str] = None,
        bucket: Optional[str] = None,
        name: Optional[str] = None,
        codec: Optional[str] = None,
        prompt_plan: Optional[Sequence[tuple[str, str]]] = None,
        **extras: Any,
    ):
        def _apply(func: Callable[..., Any]) -> Type[Any]:
            # Create the service subclass first; then resolve identity on the class
            class _FnService(BaseLLMService):
                """Auto-generated service wrapper for function-level LLM services."""

                async def on_success(self, simulation, slim):
                    sig = inspect.signature(func)
                    params = list(sig.parameters.values())
                    if len(params) >= 2:
                        return await func(simulation, slim)
                    if len(params) == 1:
                        return await func(simulation)
                    return None

            _FnService.__name__ = f"{func.__name__}_Service"
            _FnService.__module__ = getattr(func, "__module__", __name__)

            o, b, n = identity_resolver(_FnService, origin=origin, bucket=bucket, name=name)
            _FnService.origin = o
            _FnService.bucket = b
            _FnService.name = n
            _FnService.codec_name = codec or "default"
            _FnService.prompt_plan = tuple(prompt_plan or ())

            if bind_extras is not None:
                try:
                    bind_extras(_FnService, extras)
                except Exception:
                    pass

            if post_register is not None:
                try:
                    post_register(_FnService)
                except Exception:
                    pass

            return _FnService

        if _func is not None:
            return _apply(cast(Callable[..., Any], _func))
        return _apply

    return llm_service
