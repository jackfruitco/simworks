# packages/simcore_ai/src/simcore_ai/api/decorators.py
from __future__ import annotations

"""
Public facade for core decorators.

This module re-exports the instantiated, class-based decorators for the
core (provider-agnostic) layer. These decorators:

- derive a finalized Identity (namespace, kind, name) using core helpers,
- attach identity to the class (`cls.identity`, `cls.identity_obj`),
- do **not** register in the core layer (registration is wired in the Django layer).

Short names are provided for ergonomics, along with `ai_*` aliases for
projects that prefer explicit namespacing.
"""

from simcore_ai.codecs.decorators import codec as codec
from simcore_ai.codecs.decorators import ai_codec as ai_codec

from simcore_ai.services.decorators import llm_service as llm_service
from simcore_ai.services.decorators import ai_service as ai_service

from simcore_ai.promptkit.decorators import (
    prompt_section as prompt_section,
    ai_prompt_section as ai_prompt_section,
)

from simcore_ai.schemas.decorators import schema as schema
from simcore_ai.schemas.decorators import ai_schema as ai_schema

__all__ = [
    # short names
    "codec",
    "llm_service",
    "prompt_section",
    "schema",
    # namespaced aliases
    "ai_codec",
    "ai_service",
    "ai_prompt_section",
    "ai_schema",
]
