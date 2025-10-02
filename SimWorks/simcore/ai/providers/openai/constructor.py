# simcore/ai/providers/openai/constructor.py
from __future__ import annotations

from .base import OpenAIProvider
from ..base import ProviderBase


def build_from_settings(settings) -> ProviderBase:
    api_key = (getattr(settings, "OPENAI_API_KEY", None) or
               getattr(settings, "AI_API_KEY", None))
    if not api_key:
        raise RuntimeError("No OpenAI API key found. Please set OPENAI_API_KEY or AI_API_KEY in settings.")
    timeout = getattr(settings, "AI_TIMEOUT_S", 30)
    return OpenAIProvider(api_key=api_key, timeout=timeout)
