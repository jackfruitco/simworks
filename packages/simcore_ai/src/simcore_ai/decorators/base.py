# packages/simcore_ai/src/simcore_ai/decorators/base.py
from __future__ import annotations

"""
Core base decorator (class-based, no factories).

This module defines `BaseDecorator`, a callable class that implements the
dual-form decorator pattern:

    @decorator
    class Foo: ...

    @decorator(name="bar", kind="codec", namespace="chatlab")
    class Foo: ...

Key properties:
- Uses the core derivation/validation helpers (no Django imports).
- Attaches finalized identity to the decorated class:
    - `cls.identity`        -> (namespace, kind, name) tuple (for fast dict/set keys)
    - `cls.identity_obj`    -> Identity dataclass instance (for introspection)
- Registration is delegated via `get_registry()`:
    - Default returns None: registration is skipped (DEBUG logged).
    - Domain decorators override `get_registry()` to return a singleton registry.
- No token stripping or normalization logic lives here; all derivation is
  handled by helpers per the implementation plan.

IMPORTANT: This module must not import any Django modules.
"""

import logging
from typing import Any, Optional, Type, TypeVar, Callable, cast

from simcore_ai.identity.base import Identity
from simcore_ai.decorators.helpers import (
    derive_identity_core,
)

log = logging.getLogger(__name__)

T = TypeVar("T", bound=Type[Any])


class BaseDecorator:
    """
    Class-based decorator implementing the dual-form decorator pattern.

    Subclasses may override:
      - get_registry(self) -> Any | None
      - derive_identity(self, cls, *, namespace, kind, name) -> Identity
      - register(self, cls, identity: Identity) -> None  (default uses get_registry().maybe_register)

    Identity semantics:
      - Identity is computed *once* at decoration time.
      - `cls.identity` is a (namespace, kind, name) tuple for convenient equality/hash.
      - `cls.identity_obj` is the Identity dataclass instance.

    This base class performs *no* Django-aware inference; subclasses in
    simcore_ai_django override `derive_identity()` to add app-aware behavior.
    """

    # ---- public API: dual-form decorator ----
    def __call__(
            self,
            _cls: Optional[T] = None,
            *,
            namespace: Optional[str] = None,
            kind: Optional[str] = None,
            name: Optional[str] = None,
            **extras: Any,
    ) -> T | Callable[[T], T]:
        """
        Support both forms:
            @decorator
            class Foo: ...

            @decorator(namespace="x", kind="y", name="z")
            class Foo: ...
        """

        def _apply(cls: T) -> T:
            identity = self.derive_identity(
                cls,
                namespace=namespace,
                kind=kind,
                name=name,
            )
            # Attach identity in both forms
            setattr(cls, "identity_obj", identity)
            setattr(cls, "identity", identity.as_tuple3)

            # Allow subclasses to bind any extra metadata if desired
            self.bind_extras(cls, extras)

            # Perform registration (if any)
            self.register(cls, identity)
            return cls

        if _cls is not None:
            return _apply(cast(T, _cls))
        return _apply

    # ---- hooks / extension points ----

    def get_registry(self) -> Any | None:
        """
        Return the registry singleton for this decorator's domain, or None to skip registration.

        Core/base defaults to None so core decorators do not attempt registration.
        Domain decorators in `simcore_ai/*/{domain}/decorators.py` should override
        this to return the appropriate registry singleton.
        """
        return None

    def derive_identity(
            self,
            cls: Type[Any],
            *,
            namespace: Optional[str],
            kind: Optional[str],
            name: Optional[str],
    ) -> Identity:
        """
        Derive and validate identity using core helpers.

        Core precedence:
          - name: explicit (arg/attr) preserved-as-is (trim only) OR derived from class
          - namespace: arg -> class attr -> module root
          - kind: arg -> class attr -> 'default'

        Token stripping & normalization are implemented in helpers. This core
        implementation does not apply Django-specific behavior; Django subclasses
        will override to call Django-aware helpers.
        """
        # Pull any class attributes if present (explicit attrs win when helpers consult them)
        ns_attr = getattr(cls, "namespace", None)
        kind_attr = getattr(cls, "kind", None)
        name_attr = getattr(cls, "name", None)

        # Note: name token stripping in core is no-op unless caller provides tokens
        identity = derive_identity_core(
            cls,
            namespace_arg=namespace,
            kind_arg=kind,
            name_arg=name,
            namespace_attr=ns_attr,
            kind_attr=kind_attr,
            name_attr=name_attr,
            name_tokens=(),  # core has no tokens; Django layer adds them
            lower_on_derived_name=True,
        )
        return identity

    def bind_extras(self, cls: Type[Any], extras: dict[str, Any]) -> None:
        """
        Optional metadata hook. Subclasses can override to bind additional
        info from decorator kwargs onto the class (e.g., prompt plans).
        Default is a no-op.
        """
        return

    def register(self, cls: Type[Any], identity: Identity) -> None:
        """
        Default registration logic: call `get_registry().maybe_register((ns,kind,name), cls)`.
        If no registry is available (None), skip and log at DEBUG.
        """
        registry = self.get_registry()
        if registry is None:
            log.debug(
                "No registry for %s; skipping registration for %s",
                self.__class__.__name__,
                identity.as_tuple3,
            )
            return

        # Registries own duplicate vs collision handling per implementation plan.
        try:
            registry.maybe_register(identity.as_tuple3, cls)
        except Exception as exc:
            # Surface registry errors explicitly; identity validation should
            # already have run, so errors here are policy-level (e.g., collisions).
            raise
