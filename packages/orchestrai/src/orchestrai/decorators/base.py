# orchestrai/decorators/base.py


"""
Core base decorator (class-based, no factories).

This module defines `BaseDecorator`, a callable class that implements the
dual-form decorator pattern and **centralizes identity handling** via the
`orchestrai.identity` package. It does not import Django.

Usage
-----
    @decorator
    class Foo: ...

    @decorator(name="bar", kind="codec", namespace="chatlab")
    class Foo: ...

Key behaviors
-------------
- Identity derivation is delegated to `IdentityResolver` (core). Subclasses in
  other packages (e.g., Django) override `derive_identity()` to use a different
  resolver.
- The finalized identity is pinned to the class via `IdentityMixin.pin_identity()`.
  Compatibility attributes `identity_obj` and `identity_key` are not set here to
  avoid clobbering the mixin's read-only `identity` property.
- Registration is delegated to a domain registry returned by `get_registry()`.
  The base class calls **`registry.register(candidate=cls)`** (strict + idempotent). There is no `maybe_register` here. Registries read the stamped identity via the class's `identity` property (backed by the pinned identity).
- No token stripping or name normalization logic lives here; all of that is in
  the Identity layer (resolvers/utils).
"""

import logging
import os
from typing import Any, Optional, Type, TypeVar, Callable, cast

from orchestrai.tracing import service_span_sync
from orchestrai.identity import Identity
from orchestrai.identity.constants import DEFAULT_DOMAIN
from orchestrai.identity.resolvers import IdentityResolver

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Type[Any])


def _filter_trace_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    level = os.getenv("SIMCORE_TRACE_LEVEL", "info").strip().lower()
    if level not in {"debug", "info", "minimal"}:
        level = "info"
    if level == "debug":
        return attrs
    base_keys = {
        "simcore.decorator", "simcore.class", "simcore.identity",
        "simcore.tuple4.post_norm", "simcore.identity.name.explicit",
        # helpful snapshots when present
        "simcore.tuple4.raw", "simcore.tuple4.post_strip",
        "simcore.strip_tokens", "simcore.strip_tokens_list",
    }
    if level == "info":
        return {k: v for k, v in attrs.items() if k in base_keys or not k.startswith("simcore.")}
    minimal_keys = {
        "simcore.decorator", "simcore.class", "simcore.identity",
        "simcore.tuple4.post_norm", "simcore.identity.name.explicit",
    }
    return {k: v for k, v in attrs.items() if k in minimal_keys or not k.startswith("simcore.")}


class BaseDecorator:
    """Class-based decorator implementing the dual-form decorator pattern.

    Subclasses may override:
      • ``get_registry(self) -> Any | None``
      • ``derive_identity(self, cls, *, domain, namespace, group, name) -> Identity | (Identity, meta)``
      • ``bind_extras(self, cls, extras: dict[str, Any]) -> None``
      • ``register(self, candidate) -> None`` (defaults to routing a RegistrationRecord)

    Identity semantics
    ------------------
    - Identity is computed *once* at decoration time by the configured resolver.
    - The identity is pinned to the class using `IdentityMixin.pin_identity()`.
    - The class's `.identity` descriptor from `IdentityMixin` is preserved and not overwritten.
    - Compatibility attributes `identity_obj` and `identity_key` are not set here.
    - As a fallback, private cache attributes `_IdentityMixin__identity_cached` and
      `_IdentityMixin__identity_meta_cached` are set to avoid importing the mixin.
    - Subclasses in other packages (e.g., Django) may override `derive_identity()` to call their resolver.
    """

    default_domain: str | None = DEFAULT_DOMAIN
    default_namespace: str | None = None
    default_group: str | None = None

    def __init__(self, *, resolver: IdentityResolver | None = None) -> None:
        # Allow per-instance override; default to core resolver
        self.resolver: IdentityResolver = resolver or IdentityResolver()

    # ---------------- public API: dual-form decorator ----------------
    def __call__(
        self,
        _cls: Optional[T] = None,
        *,
        domain: Optional[str] = None,
        namespace: Optional[str] = None,
        group: Optional[str] = None,
        kind: Optional[str] = None,
        name: Optional[str] = None,
        **extras: Any,
    ) -> T | Callable[[T], T]:
        """Support both forms:

            @decorator
            class Foo: ...

            @decorator(domain="d", namespace="x", group="y", name="z")
            class Foo: ...
        """

        def _apply(cls: T) -> T:
            fqcn = f"{cls.__module__}.{cls.__name__}"

            # 1) Derive identity (subclasses may return (Identity, meta))
            result = self.derive_identity(
                cls,
                domain=domain,
                namespace=namespace,
                group=group or kind,
                name=name,
            )
            if isinstance(result, tuple) and len(result) == 2:
                identity, meta = result  # type: ignore[misc]
            else:
                identity, meta = result, {}

            # 2) Pin identity to class (avoid clobbering .identity descriptor)
            pin_func = getattr(cls, "pin_identity", None)
            if callable(pin_func):
                pin_func(identity, meta)
            else:
                # fallback: set private cache attributes to avoid importing IdentityMixin here
                setattr(cls, "_IdentityMixin__identity_cached", identity)
                setattr(cls, "_IdentityMixin__identity_meta_cached", meta)

            # 3) Bind any extra decorator metadata
            self.bind_extras(cls, extras)

            # 4) Register (if a registry is present)
            self.register(cls)

            # 5) Emit a single trace span *after* successful registration with rich attributes
            final_label = identity.as_str
            span_attrs_raw = {
                "simcore.decorator": self.__class__.__name__,
                "simcore.class": fqcn,
                "simcore.identity": final_label,
                # Optional debug/meta provided by resolvers (e.g., ai.strip_tokens, ai.tuple4.*)
                **({} if not isinstance(meta, dict) else meta),
                # Echo e    xplicit args if provided (drop Nones below)
                "simcore.domain_arg": domain,
                "simcore.namespace_arg": namespace,
                "simcore.group_arg": group or kind,
                "simcore.name_arg": name,
            }
            span_attrs = {k: v for k, v in span_attrs_raw.items() if v is not None}
            span_attrs = _filter_trace_attrs(span_attrs)
            with service_span_sync(f"simcore.decorator.apply ({cls.__name__})", attributes=span_attrs):
                label = getattr(self, "log_category", None) or self.__class__.__name__
                label = str(label).upper()
                logger.info("[%s] ✅ discovered `%s`", label, identity.as_str)
                # if logger.isEnabledFor(logging.DEBUG):
                #     logger.debug(" -- fqcn: %s" % fqcn)
                #     logger.debug(" -- attributes: %s" % span_attrs.__repr__())

            return cls

        # IMPORTANT: return the applied class when used as @decorator, or return
        # the decorator function when used as @decorator(...)
        if _cls is not None:
            return _apply(cast(T, _cls))
        return _apply

    # ---------------- hooks / extension points ----------------
    def get_registry(self) -> Any | None:
        """Return the registry singleton for this decorator's domain, or **None** to skip.

        The core base returns **None** so core decorators do not attempt registration.
        Domain decorators (codecs/services/prompt sections/schemas) should override
        this and return the appropriate registry singleton.
        """
        return None

    def derive_identity(
        self,
        cls: Type[Any],
        *,
        domain: Optional[str],
        namespace: Optional[str],
        group: Optional[str],
        name: Optional[str],
    ) -> tuple[Identity, dict[str, Any] | None]:
        """Derive + validate identity using the configured resolver (core default).

        Precedence (core):
          - name: explicit (arg/attr) preserved-as-is (trim only) or derived from class
          - domain: arg → class attr → decorator default → error
          - namespace: arg → class attr → decorator default → module root → "default"
          - group: arg → class attr → decorator default → "default" (legacy `kind` accepted)

        Token stripping & normalization are implemented in the Identity layer.
        """
        context = {
            "default_domain": getattr(self, "default_domain", DEFAULT_DOMAIN),
            "default_namespace": getattr(self, "default_namespace", None),
            "default_group": getattr(self, "default_group", None),
        }
        identity, meta = self.resolver.resolve(
            cls,
            domain=domain,
            namespace=namespace,
            group=group,
            name=name,
            context=context,
        )
        return identity, meta

    def bind_extras(self, cls: Type[Any], extras: dict[str, Any]) -> None:  # pragma: no cover - default no-op
        """Optional metadata hook for domain decorators (e.g., prompt plans)."""
        return

    def register(self, candidate: Type[Any]) -> None:
        """Default registration logic.

        - Retrieves a registry via ``get_registry()``.
        - If present, calls **``registry.register(candidate=candidate)``** (strict + idempotent).
        - If no registry, logs at DEBUG and returns.
        """
        from orchestrai.registry import RegistrationRecord, route_registration

        registry = self.get_registry()
        if registry is None:
            logger.debug(
                "No registry for %s; queuing registration for %s",
                self.__class__.__name__,
                f"{candidate.__module__}.{candidate.__name__}",
            )
        route_registration(
            RegistrationRecord(
                component=candidate,
                identity=Identity.get_for(candidate),
            )
        )
        logger.debug(
            "registered %s",
            f"{candidate.__name__}",
        )
