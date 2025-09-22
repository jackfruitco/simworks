# simcore/ai/__init__.py
from .promptkit import PromptEngine
from .utils import (
    build_output_schema,
    persist_metadata,
    persist_message,
    resolve_initial_section
)

from .version import VERSION

def get_ai_client():
    # Lazy import to avoid circular import
    from .bootstrap import get_ai_client as _get_ai_client
    return _get_ai_client()

def get_default_model():
    # Lazy import to avoid circular import
    from .bootstrap import get_default_model as _get_default_model
    return _get_default_model()

__all__ = [
    "get_ai_client",
    "get_default_model",
    "PromptEngine",
    "build_output_schema",
    "persist_metadata",
    "persist_message",
    "resolve_initial_section",
    "VERSION",
]
