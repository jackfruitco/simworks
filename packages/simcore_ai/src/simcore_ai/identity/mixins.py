# packages/simcore_ai/src/simcore_ai/identity/mixins.py
from __future__ import annotations

from typing import ClassVar, Optional


class IdentityMixin:
    """Lightweight class-level identity hints.

    This mixin intentionally performs **no derivation**. Values may be set by
    subclasses or left as ``None`` for the resolver/decorators to derive.

    Vocabulary:
        - ``namespace``: top-level grouping (e.g., app/package/org)
        - ``kind``: functional group within the namespace (e.g., codec, service)
        - ``name``: specific identifier within (namespace, kind)

    Example:
        >>> class MyNs(IdentityMixin):
        ...     namespace = "chatlab"
        >>> class MyKind(IdentityMixin):
        ...     kind = "codec"
        >>> class MyThing(MyNs, MyKind):
        ...     name = "patient-initial"
    """

    # Class-level identity hints (may be overridden by subclasses)
    namespace: ClassVar[Optional[str]] = None
    kind: ClassVar[Optional[str]] = None
    name: ClassVar[Optional[str]] = None

    # Optional marker for abstract identity-bearing mixins (not used by core logic,
    # but available for frameworks that want to skip auto-resolution on abstract bases)
    __identity_abstract__: ClassVar[bool] = False

    @classmethod
    def identity_key(cls) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Return the raw (namespace, kind, name) triple as declared on the class."""
        return (cls.namespace, cls.kind, cls.name)

    @classmethod
    def identity_str(cls) -> str:
        ns, kd, nm = cls.namespace, cls.kind, cls.name
        return f"{cls.__name__}(namespace={ns!r}, kind={kd!r}, name={nm!r})"

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.identity_str()

    def __init_subclass__(cls, **kwargs) -> None:  # pragma: no cover - simple type guard
        super().__init_subclass__()
        # Enforce that identity hints, if provided, are strings (or None)
        for attr in ("namespace", "kind", "name"):
            val = getattr(cls, attr, None)
            if val is not None and not isinstance(val, str):
                raise TypeError(f"{cls.__name__}.{attr} must be a str or None")
