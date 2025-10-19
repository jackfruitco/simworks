"""
simcore_ai — Core AI infrastructure layer for SimWorks.

This package provides the foundational abstractions and logic for
AI-driven simulation services, including:

- Provider management (`simcore_ai.providers`)
- Client management (`simcore_ai.client`)
- Codec system for structured AI input/output (`simcore_ai.codecs`)
- Core service orchestration and identity model (`simcore_ai.services`, `simcore_ai.types.identity`)
- Unified exception hierarchy (`simcore_ai.exceptions`)

This core package is framework-agnostic: it does not depend on Django
or any specific runtime environment. Higher-level integrations (e.g.,
`simcore_ai_django`) extend this base layer with persistence, signals,
and framework utilities.

Import Guidelines:
------------------
- Use `simcore_ai.client` for interacting with AI providers or creating clients.
- Use `simcore_ai.services` for defining LLM services.
- Use `simcore_ai.codecs` for encoding/decoding structured LLM data.
- Use `simcore_ai.exceptions` for standardized error handling.
- Import `Identity` from `simcore_ai.types.identity` for consistent naming and scoping.

"""
from .client import AIClient, create_client, get_ai_client, set_default_client
from .client.schemas import AIProviderConfig, AIClientRegistration
from .codecs import BaseLLMCodec, codec
from .services import BaseLLMService
from .tracing import (
    inject_trace, extract_trace, get_tracer,
    service_span, service_span_sync
)
from .types import Identity

__all__ = [
    "AIProviderConfig",
    "AIClientRegistration",
    "AIClient",
    "create_client",
    "get_ai_client",
    "set_default_client",
    "BaseLLMService",
    "BaseLLMCodec",
    "codec",
    "Identity",
    "inject_trace",
    "extract_trace",
    "get_tracer",
    "service_span",
    "service_span_sync"
]

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("simcore_ai")
except PackageNotFoundError:
    __version__ = "0.0.0"
