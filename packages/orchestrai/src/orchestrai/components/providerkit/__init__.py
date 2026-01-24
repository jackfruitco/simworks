"""
OrchestrAI ProviderKit Module (DEPRECATED).

.. deprecated:: 0.5.0
    This module is deprecated and will be removed in OrchestrAI 1.0.
    Pydantic AI handles provider abstraction natively.
    Use :class:`orchestrai.components.services.PydanticAIService` instead.
"""
import warnings

warnings.warn(
    "orchestrai.components.providerkit is deprecated and will be removed in OrchestrAI 1.0. "
    "Pydantic AI handles provider abstraction natively.",
    DeprecationWarning,
    stacklevel=2,
)

from .provider import *
from .conf_models import ProvidersSettings, ProviderSettingsEntry
from .factory import *

__all__ = [
    "BaseProvider",
    "ProviderConfig",
    "ProvidersSettings",
    "ProviderSettingsEntry",
]