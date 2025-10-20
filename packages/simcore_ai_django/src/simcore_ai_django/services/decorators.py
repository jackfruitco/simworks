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

from simcore_ai.decorators.base import make_fn_service_decorator
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


# Build the dual-form function→service decorator using the shared factory and Django resolver.
llm_service = make_fn_service_decorator(
    identity_resolver=django_identity_resolver,
    post_register=_post_register_service,
)

__all__ = ["llm_service"]
