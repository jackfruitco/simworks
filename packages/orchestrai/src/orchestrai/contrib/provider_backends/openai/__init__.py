# orchestrai/contrib/provider_backends/openai/__init__.py
"""OpenAI Responses API provider backend.

This module provides a complete provider backend for OpenAI's Responses API,
including:

- **OpenAIResponsesProvider**: Main provider class
- **Schema Adapters**: Transform schemas for OpenAI compatibility
- **Output Adapters**: Process OpenAI-specific outputs (e.g., images)
- **Request Builder**: Build API-compliant request payloads
- **Constants**: Shared configuration values
"""
from . import output_adapters, schema_adapters
from .constants import API_SURFACE, API_VERSION, DEFAULT_MODEL, DEFAULT_TIMEOUT_S, PROVIDER_NAME
from .openai import OpenAIResponsesProvider
from .output_adapters import ImageGenerationOutputAdapter
from .request_builder import build_responses_request
from .schema_adapters import FlattenUnions, OpenaiWrapper

__all__ = [
    # Provider
    "OpenAIResponsesProvider",
    # Constants
    "PROVIDER_NAME",
    "API_SURFACE",
    "API_VERSION",
    "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT_S",
    # Request building
    "build_responses_request",
    # Schema adapters
    "schema_adapters",
    "OpenaiWrapper",
    "FlattenUnions",
    # Output adapters
    "output_adapters",
    "ImageGenerationOutputAdapter",
]
