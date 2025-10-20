# simcore_ai_django/services/decorators.py
"""Django-aware LLM service decorator built on the shared base factory.

This module wires the Django-facing `llm_service` to the core dual-form
function→service factory using a Django-aware identity resolver. It also
attempts to register services with the (optional) ServicesRegistry and applies
collision resolution without raising at import time.

Behavior:
- Dual-form usage: `@llm_service` or `@llm_service(origin=..., bucket=..., name=..., codec=..., prompt_plan=...)`.
- Identity: resolved on the **generated service class** using Django-aware
  rules (leaf-class based name, standardized suffix stripping, app/settings
  tokens). `bucket` defaults to "default" when unset.
- Registry: if `ServicesRegistry` is available, collisions are resolved via
  `resolve_collision_django` before registering the class; otherwise, this is a
  no-op to keep imports safe.
"""
from __future__ import annotations

import inspect
from simcore_ai.decorators.base import (
    make_class_decorator,
    make_fn_service_decorator,
)
from simcore_ai_django.identity import resolve_collision_django
from simcore_ai_django.identity.resolvers import django_identity_resolver


def _post_register_service(cls: type) -> None:
    """Guarded post-register hook for Django services.

    - If the ServicesRegistry is present, detect tuple³ collisions and resolve
      them using `resolve_collision_django`, then register the class.
    - If not present (or raises), silently no-op to avoid import-time failures.
    """
    try:
        # Local import to avoid hard dependency at import time
        from simcore_ai.services.registry import ServicesRegistry  # type: ignore
    except Exception:
        return

    try:
        def _exists(t: tuple[str, str, str]) -> bool:
            try:
                return bool(ServicesRegistry.has(*t))
            except Exception:
                return False

        # Resolve collisions if any, then mutate class identity before register
        o, b, n = getattr(cls, "origin", ""), getattr(cls, "bucket", ""), getattr(cls, "name", "")
        o, b, n = resolve_collision_django("service", (o, b, n), exists=_exists)
        setattr(cls, "origin", o)
        setattr(cls, "bucket", b)
        setattr(cls, "name", n)

        # Finally, register the CLASS with the registry
        try:
            ServicesRegistry.register(cls)  # type: ignore[attr-defined]
        except Exception:
            # Tolerate duplicates or registry-specific errors during autoreload
            pass
    except Exception:
        # Never crash during module import
        return



# Build both variants and expose a single smart decorator that dispatches based on the target.
_class_dec = make_class_decorator(
    identity_resolver=django_identity_resolver,
    post_register=_post_register_service,
)
_fn_dec = make_fn_service_decorator(
    identity_resolver=django_identity_resolver,
    post_register=_post_register_service,
)

def llm_service(_obj=None, /, **kw):
    """
    Smart decorator for Django services.

    - If applied to a **class**, preserves the class' MRO (keeps mixins like
      ServiceExecutionMixin so `.execute()` remains available).
    - If applied to an **async function**, generates a `_FnService(BaseLLMService)`
      wrapper and registers it with Django-aware identity.

    Works in both forms:
        @llm_service
        class MyClassService(...): ...

        @llm_service
        async def my_fn_service(...): ...

        @llm_service(origin="chatlab", bucket="default", name="generate_initial_response")
        class/fn ...
    """
    # Called as @llm_service without params
    if _obj is not None:
        if inspect.isclass(_obj):
            return _class_dec(_obj)
        return _fn_dec(_obj)

    # Called as @llm_service(...)
    def _apply(obj):
        if inspect.isclass(obj):
            return _class_dec(origin=kw.get("origin"), bucket=kw.get("bucket"), name=kw.get("name"), **{k: v for k, v in kw.items() if k not in {"origin", "bucket", "name"}})(obj)
        return _fn_dec(**kw)(obj)

    return _apply

__all__ = ["llm_service"]
