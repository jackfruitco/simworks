# simcore_ai_django/identity/mixins.py
from __future__ import annotations

import logging

from simcore_ai.identity import IdentityMixin
from .utils import derive_django_identity_for_class

logger = logging.getLogger(__name__)


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


    # __identity_abstract__ = True


    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # skip deriving identity for mixin classes
        if (
                cls.__name__.endswith("Mixin")
                or cls.__module__.endswith(".mixins")
                or getattr(cls, "__identity_abstract__", False)
        ):
            return

        try:
            if not all(getattr(cls, k, None) for k in ("origin", "bucket", "name")):
                cls.origin, cls.bucket, cls.name = cls.identity_tuple()
        except Exception:
            # Never block Django startup; log at debug
            logger.debug("Skipping identity init for %s", cls, exc_info=True)
