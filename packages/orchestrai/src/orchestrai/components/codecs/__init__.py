# orchestrai/components/codecs/__init__.py
"""
OrchestrAI Codecs Module (DEPRECATED).

.. deprecated:: 0.5.0
    This module is deprecated and will be removed in OrchestrAI 1.0.
    Pydantic AI handles structured output validation natively via result_type.
    Use plain Pydantic models as response_schema instead.
"""
import warnings

warnings.warn(
    "orchestrai.components.codecs is deprecated and will be removed in OrchestrAI 1.0. "
    "Pydantic AI handles validation natively via result_type.",
    DeprecationWarning,
    stacklevel=2,
)

from .codec import BaseCodec

__all__ = (
    "BaseCodec",
)