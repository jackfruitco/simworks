# simcore_ai_django/promptkit/decorators.py
from __future__ import annotations

import logging
import re
from typing import Type, Optional

from django.apps import apps as django_apps

from simcore_ai.promptkit.registry import PromptRegistry
from simcore_ai.promptkit.types import PromptSection
from simcore_ai.types.identity.base import Identity

logger = logging.getLogger(__name__)

_SUFFIX_RE = re.compile(
    r"(PromptScenario|Scenario|PromptSection|Prompt|Section)$", re.IGNORECASE
)


def _infer_app_label(py_module: str) -> Optional[str]:
    """Return the Django app label that contains the given module path."""
    try:
        cfg = django_apps.get_containing_app_config(py_module)
        return getattr(cfg, "label", None)
    except Exception:
        return None


def _derive_name_from_class(cls_name: str) -> str:
    """Strip common suffixes and normalize to a slug-like lower name."""
    base = _SUFFIX_RE.sub("", cls_name).strip()
    # convert CamelCase -> snake-ish -> kebab-ish -> plain lower
    # we rely on Identity normalization later, so keep it simple:
    return base or cls_name


def _ensure_identity(cls: Type[PromptSection]) -> None:
    """If a PromptSection class lacks an Identity, synthesize one from Django context."""
    ident = getattr(cls, "identity", None)
    has_explicit = isinstance(ident, Identity)
    has_parts = all(isinstance(getattr(cls, k, None), str) and getattr(cls, k) for k in ("origin", "bucket", "name"))

    if has_explicit or has_parts:
        return

    origin = _infer_app_label(cls.__module__) or "app"
    bucket = getattr(cls, "bucket", None) or "default"
    derived = _derive_name_from_class(cls.__name__)
    name = getattr(cls, "name", None) or derived

    cls.identity = Identity.from_parts(origin=origin, bucket=bucket, name=name)  # type: ignore[attr-defined]
    logger.info(
        "Prompt identity inferred for %s -> %s",
        cls.__name__,
        cls.identity.to_string(),  # type: ignore[attr-defined]
    )


def _register_prompt_section(cls: Type[PromptSection]) -> Type[PromptSection]:
    _ensure_identity(cls)
    PromptRegistry.register(cls)
    setattr(cls, "_is_registered_prompt", True)
    return cls


# Public decorators (Django-aware, identity defaults)
def prompt_section(cls: Type[PromptSection]) -> Type[PromptSection]:
    """Django-aware decorator that registers a PromptSection and auto-fills identity.

    If `identity` (or origin/bucket/name) is not declared on the class, we will:
      - set `origin` to the Django app label for the class' module
      - set `bucket` to `"default"`
      - derive `name` from the class name with common suffixes removed
    """
    return _register_prompt_section(cls)


# If you add scenarios later, they can reuse the same identity rules
prompt_scenario = prompt_section
