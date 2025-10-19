# simcore_ai_django/identity/mixins.py
from __future__ import annotations

from simcore_ai.identity import IdentityMixin
from simcore_ai_django.identity import derive_django_identity_for_class

class DjangoIdentityMixin(IdentityMixin):
    """
    Django-aware identity mixin.

    - origin/bucket/name may be declared as class attrs; if absent, derive
      from Django app label (origin), default bucket, and stripped class name.
    - All parts normalize to snake_case.
    """
    @classmethod
    def identity_tuple(cls) -> tuple[str, str, str]:
        o = getattr(cls, "origin", None)
        b = getattr(cls, "bucket", None)
        n = getattr(cls, "name", None)
        return derive_django_identity_for_class(cls, origin=o, bucket=b, name=n)

    @classmethod
    def identity_str(cls) -> str:
        o, b, n = cls.identity_tuple()
        return f"{o}.{b}.{n}"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "origin", None) or not getattr(cls, "bucket", None) or not getattr(cls, "name", None):
            cls.origin, cls.bucket, cls.name = cls.identity_tuple()