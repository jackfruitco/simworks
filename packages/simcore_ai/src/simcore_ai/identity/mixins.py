# packages/simcore_ai/src/simcore_ai/identity/mixins.py
from __future__ import annotations

from threading import RLock
from typing import ClassVar, Optional, Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid import cycles at import time
    from simcore_ai.identity import Identity

class _IdentityAccessor:
    """Descriptor that returns the resolved Identity for a class or instance."""
    def __get__(self, obj, owner):
        cls = owner if obj is not None else owner  # explicit for readability
        # Late import to avoid cycles
        # Call through to the mixin's resolver-backed method
        return cls.resolve_identity()

class IdentityMixin:
    """Centralized, resolver-driven class identity.

    This mixin exposes a consistent identity surface for all identity-bearing
    classes (codecs, prompt sections, services, response schemas).

    Design:
      - Identity is *class-level* semantics: derive once per class and cache.
      - Instances read `self.identity` (read-only) which returns the class identity.
      - Resolution is delegated to Identity.resolve.for_(...). Mixins delegate to that API.
      - Decorators/registration may *pin* identity via `pin_identity(...)`.

    Class attributes (hints only):
      namespace/kind/name: Optional[str]
        Hints consumed by the resolver. They are not required.

    Resolution:
      Centralized via Identity.resolve.for_(...). Mixins delegate to that API.

    Public API:
      - cls.identity_resolved() -> Identity
      - cls.identity_meta() -> dict[str, Any]
      - cls.pin_identity(identity: Identity) -> None
      - instance/class .identity -> Identity  (read-only descriptor)
    """

    # ----- identity hints (optional) -----
    namespace: ClassVar[Optional[str]] = None
    kind: ClassVar[Optional[str]] = None
    name: ClassVar[Optional[str]] = None

    __identity_abstract__: ClassVar[bool] = False

    # ----- internal cache (per-class) -----
    __identity_cached: ClassVar[Optional["Identity"]] = None
    __identity_meta_cached: ClassVar[Optional[dict[str, Any]]] = None
    __identity_lock: ClassVar[RLock] = RLock()

    # Expose a single, simple surface: ExampleCodec.identity -> Identity
    identity = _IdentityAccessor()

    # ------------------------- class utilities -------------------------


    @classmethod
    def resolve_identity(cls) -> "Identity":
        """Resolve and cache the class identity via Identity.resolve.for_()."""
        cached = cls.__identity_cached
        if cached is not None:
            return cached

        # Late import to avoid cycles
        from simcore_ai.identity.identity import Identity as _Identity

        with cls.__identity_lock:
            if cls.__identity_cached is not None:
                return cls.__identity_cached

            # Support both legacy (namespace/kind/name) and newer (origin/bucket/name) hints.
            # Prefer explicit hints present on the class; fall back to legacy names.
            hints = {}

            hints.update(
                namespace=getattr(cls, "namespace", None),
                kind=getattr(cls, "kind", None),
                name=getattr(cls, "name", None),
            )

            ident, meta = _Identity.resolve.for_(cls, **hints, context=None)
            cls.__identity_cached = ident
            cls.__identity_meta_cached = dict(meta or {})
            return ident

    @classmethod
    def identity_meta(cls) -> dict[str, Any]:
        """Return resolver meta for tracing/debugging (cached)."""
        _ = cls.resolve_identity()  # ensure resolved
        return dict(cls.__identity_meta_cached or {})


    @classmethod
    def pin_identity(cls, identity: "Identity") -> None:
        """Explicitly pin a class's identity (used by decorators/registry).

        This sets the cache to a specific Identity and clears meta. Intended for
        explicit, authoritative assignments done at registration time.
        """
        with cls.__identity_lock:
            cls.__identity_cached = identity
            cls.__identity_meta_cached = {"ai.identity.source": "pinned"}

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