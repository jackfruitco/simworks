# packages/simcore_ai/src/simcore_ai/identity/mixins.py
from __future__ import annotations

from typing import ClassVar, Optional, Type, Any
from threading import RLock
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid import cycles at import time
    from simcore_ai.identity.base import Identity
    from simcore_ai.identity.resolvers import IdentityResolver

class IdentityMixin:
    """Centralized, resolver-driven class identity.

    This mixin exposes a consistent identity surface for all identity-bearing
    classes (codecs, prompt sections, services, response schemas).

    Design:
      - Identity is *class-level* semantics: derive once per class and cache.
      - Instances read `self.identity` (read-only) which returns the class identity.
      - Resolution is pluggable via `identity_resolver_cls` (core vs Django).
      - Decorators/registration may *pin* identity via `pin_identity(...)`.

    Class attributes (hints only):
      namespace/kind/name: Optional[str]
        Hints consumed by the resolver. They are not required.

    Override points:
      identity_resolver_cls: ClassVar[Type[IdentityResolver]]
        Defaults to core resolver in core; Django layers can override on their mixin.

    Public API:
      - cls.identity_resolved() -> Identity
      - cls.identity_meta() -> dict[str, Any]
      - cls.identity_as_tuple3() -> tuple[str, str, str]
      - cls.identity_as_str() -> str
      - cls.pin_identity(identity: Identity) -> None
      - instance.identity -> Identity  (read-only)
    """

    # ----- identity hints (optional) -----
    namespace: ClassVar[Optional[str]] = None
    kind: ClassVar[Optional[str]] = None
    name: ClassVar[Optional[str]] = None

    __identity_abstract__: ClassVar[bool] = False

    # ----- resolver selection (override in framework mixins, e.g., Django) -----
    identity_resolver_cls: ClassVar[Optional[Type["IdentityResolver"]]] = None  # set in core/django layers

    # ----- internal cache (per-class) -----
    __identity_cached: ClassVar[Optional["Identity"]] = None
    __identity_meta_cached: ClassVar[Optional[dict[str, Any]]] = None
    __identity_lock: ClassVar[RLock] = RLock()

    # ------------------------- class utilities -------------------------

    @classmethod
    def identity_key(cls) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Raw hints as declared on the class (no derivation)."""
        return (cls.namespace, cls.kind, cls.name)

    @classmethod
    def identity_resolved(cls) -> "Identity":
        """Resolve (or return cached) class identity via the configured resolver."""
        # Fast path
        cached = cls.__identity_cached
        if cached is not None:
            return cached

        # Late imports to avoid cycles
        from simcore_ai.identity.base import Identity
        from simcore_ai.identity.resolvers import IdentityResolver, resolve_identity

        # Determine resolver class
        resolver_cls = cls.identity_resolver_cls or IdentityResolver
        # Instantiate if needed
        resolver = resolver_cls() if isinstance(resolver_cls, type) else resolver_cls

        with cls.__identity_lock:
            if cls.__identity_cached is not None:
                return cls.__identity_cached  # another thread won the race

            # Build kwargs from hints; let resolver apply precedence
            ns, kd, nm = cls.namespace, cls.kind, cls.name
            ident, meta = resolver.resolve(cls, namespace=ns, kind=kd, name=nm, context=None)

            cls.__identity_cached = ident
            cls.__identity_meta_cached = dict(meta or {})
            return ident

    @classmethod
    def identity_meta(cls) -> dict[str, Any]:
        """Return resolver meta for tracing/debugging (cached)."""
        _ = cls.identity_resolved()  # ensure resolved
        return dict(cls.__identity_meta_cached or {})

    @classmethod
    def identity_as_tuple3(cls) -> tuple[str, str, str]:
        ident = cls.identity_resolved()
        return ident.as_tuple3

    @classmethod
    def identity_as_str(cls) -> str:
        ident = cls.identity_resolved()
        return ident.as_str

    @classmethod
    def pin_identity(cls, identity: "Identity") -> None:
        """Explicitly pin a class's identity (used by decorators/registry).

        This sets the cache to a specific Identity and clears meta. Intended for
        explicit, authoritative assignments done at registration time.
        """
        with cls.__identity_lock:
            cls.__identity_cached = identity
            cls.__identity_meta_cached = {"ai.identity.source": "pinned"}

    # ------------------------- instance surface -------------------------

    @property
    def identity(self) -> "Identity":
        """Read-only instance view of the class identity."""
        return type(self).identity_resolved()

    # Convenience (human-friendly) string for instances
    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"{type(self).__name__}<{type(self).identity_as_str()}>"

    def __init_subclass__(cls, **kwargs) -> None:  # pragma: no cover - light guardrails
        super().__init_subclass__(**kwargs)
        # Enforce identity hint types if provided
        for attr in ("namespace", "kind", "name"):
            val = getattr(cls, attr, None)
            if val is not None and not isinstance(val, str):
                raise TypeError(f"{cls.__name__}.{attr} must be a str or None")
        # Reset caches for subclasses so each class resolves independently
        cls.__identity_cached = None
        cls.__identity_meta_cached = None