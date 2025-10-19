# simcore_ai/types/identity/mixins.py
from __future__ import annotations


from typing import ClassVar, Optional

class IdentityMixin:
    """Class-level identity hints for providers/components.

    Example:
        ```
        from simcore_ai.types.identity.mixins import IdentityMixin

        class MyOriginMixin(IdentityMixin):
            origin = "my_origin"

        class MyBucketMixin(IdentityMixin):
            bucket = "my_bucket"
        ```
    """
    origin: ClassVar[Optional[str]] = None
    bucket: ClassVar[Optional[str]] = None
    name: ClassVar[Optional[str]] = None

    @classmethod
    def identity_key(cls) -> tuple[str | None, str | None, str | None]:
        return (cls.origin, cls.bucket, cls.name)

    @classmethod
    def identity_str(cls) -> str:
        o, b, n = cls.origin, cls.bucket, cls.name
        return f"{cls.__name__}(origin={o!r}, bucket={b!r}, name={n!r})"

    def __str__(self) -> str:
        return self.identity_str()

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        for attr in ("origin", "bucket", "name"):
            val = getattr(cls, attr, None)
            if val is not None and not isinstance(val, str):
                raise TypeError(f"{cls.__name__}.{attr} must be a str or None")
