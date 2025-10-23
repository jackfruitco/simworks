# simcore_ai_django/identity/mixins.py
from __future__ import annotations

import logging

from simcore_ai.identity import IdentityMixin
from simcore_ai.decorators.helpers import derive_name, normalize_name
from simcore_ai_django.decorators.helpers import (
    derive_namespace_django,
    get_app_tokens_for_name,
    strip_name_tokens_django,
)

logger = logging.getLogger(__name__)


class DjangoIdentityMixin(IdentityMixin):
    """
    Django-aware identity mixin.

    - namespace/kind/name may be declared as class attrs; if absent, derive
      from Django app label (namespace), default kind, and stripped class name.
    - All parts normalize to snake_case.
    """

    @classmethod
    def identity_tuple(cls) -> tuple[str, str, str]:
        # Resolve namespace via Django helpers (argless here, we only have attrs)
        ns = derive_namespace_django(
            cls,
            namespace_arg=getattr(cls, "namespace", None),
            namespace_attr=getattr(cls, "namespace", None),
        )

        # Kind: prefer explicit class attr; otherwise default to "default" (mixin should not impose domain)
        kd = getattr(cls, "kind", None) or "default"

        # Name: explicit attr preserved; otherwise derive from class name with Django/app/global tokens
        name_attr = getattr(cls, "name", None)
        explicit = name_attr is not None
        raw_name = derive_name(
            cls,
            name_arg=name_attr,  # if explicit, derive_name returns it; else derives from cls.__name__
            name_attr=name_attr,
            derived_lower=True,
        )
        if explicit:
            nm = normalize_name(raw_name)
        else:
            tokens = get_app_tokens_for_name(cls)
            stripped = strip_name_tokens_django(raw_name, tokens=tokens)
            post_strip = stripped or raw_name
            nm = normalize_name(post_strip or cls.__name__)

        # Defensive: avoid redundant namespace prefix in name (e.g., "chatlab-…")
        ns_prefix = f"{ns}-"
        if nm.startswith(ns_prefix):
            nm = nm[len(ns_prefix):]

        return ns, kd, nm

    @classmethod
    def identity_str(cls) -> str:
        o, b, n = cls.identity_tuple()
        return f"{o}.{b}.{n}"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Skip deriving identity for mixins or classes explicitly marked abstract on themselves.
        # IMPORTANT: treat __identity_abstract__ as NON-INHERITING by consulting cls.__dict__ only.
        if (
                cls.__name__.endswith("Mixin")
                or cls.__module__.endswith(".mixins")
                or cls.__dict__.get("__identity_abstract__", False)
        ):
            return

        try:
            # Only derive when any part is missing; never overwrite explicit attributes.
            if not all(getattr(cls, k, None) for k in ("namespace", "kind", "name")):
                cls.namespace, cls.kind, cls.name = cls.identity_tuple()
        except Exception:
            # Never block Django startup; log at debug
            logger.debug("Skipping identity init for %s", cls, exc_info=True)
