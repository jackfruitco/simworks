"""
orchestrai — Core AI infrastructure layer for SimWorks.

This package provides the foundational abstractions and logic for
AI-driven simulation services, including:

- Provider management (`orchestrai.providers`)
- Client management (`orchestrai.client`)
- Codec system for structured AI input/output (`orchestrai.codecs`)
- Core service orchestration and identity model (`orchestrai.services`, `orchestrai.types.identity`)
- Unified exception hierarchy (`orchestrai.exceptions`)

This core package is framework-agnostic: it does not depend on Django
or any specific runtime environment. Higher-level integrations (e.g.,
`orchestrai_django`) extend this base layer with persistence, signals,
and framework utilities.

Import Guidelines:
------------------
- Use `orchestrai.client` for interacting with AI providers or creating clients.
- Use `orchestrai.services` for defining LLM services.
- Use `orchestrai.codecs` for encoding/decoding structured LLM data.
- Use `orchestrai.exceptions` for standardized error handling.
- Import `Identity` from `orchestrai.types.identity` for consistent naming and scoping.

"""
# from .client import OrcaClient, create_client, get_ai_client, set_default_client
# from .client.schemas import ProviderConfig, OrcaClientRegistration
# from .codecs import BaseCodec, codec
# from .services import BaseService
# from .identity import Identity
# from .tracing import (
#     inject_trace, extract_trace, get_tracer,
#     service_span, service_span_sync
# )
# from .types import Identity
#
# __all__ = [
#     "ProviderConfig",
#     "OrcaClientRegistration",
#     "OrcaClient",
#     "create_client",
#     "get_ai_client",
#     "set_default_client",
#     "BaseService",
#     "BaseCodec",
#     "codec",
#     "Identity",
#     "inject_trace",
#     "extract_trace",
#     "get_tracer",
#     "service_span",
#     "service_span_sync"
# ]

from importlib.metadata import PackageNotFoundError, version

from .app import OrchestrAI
from ._state import current_app, get_current_app

try:
    __version__ = version("orchestrai")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "OrchestrAI",
    "current_app",
    "get_current_app",
]
