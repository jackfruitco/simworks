# packages/simcore_ai_django/src/simcore_ai_django/api/decorators.py
from __future__ import annotations

"""
Public facade for **Django-aware** decorators.

This module re-exports the instantiated, class-based decorators from the
Django layer so app code can import them from a single, stable location:

    from simcore_ai_django.api.decorators import llm_service, codec, prompt_section, schema

These decorators:
- derive a finalized Identity `(namespace, kind, name)` using the Django-aware
  pipeline (AppConfig label/name, name-only token stripping),
- attach identity to the class (`cls.identity`, `cls.identity_obj`), and
- **register with the Django registries**, where duplicate vs collision policy
  is enforced via `SIMCORE_COLLISIONS_STRICT`.

Note: Collision rewriting (e.g., appending `-2`) is **not** performed here; that
policy lives in the registries. Decorators may expose an
`allow_collision_rewrite()` hint, but by default it is disabled and should not
be used in production.
"""

from simcore_ai_django.codecs.decorators import codec as codec
from simcore_ai_django.services.decorators import llm_service as llm_service
from simcore_ai_django.promptkit.decorators import (
    prompt_section as prompt_section,
)
from simcore_ai_django.schemas.decorators import schema as schema

__all__ = [
    "codec",
    "llm_service",
    "prompt_section",
    "schema",
]
