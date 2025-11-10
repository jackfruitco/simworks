"""
This module provides a collection of Django integration components specifically
designed for AI-driven workflows. It includes codecs, services, and prompt
mechanisms to enhance interactive machine learning applications.

The module encapsulates various utility classes such as base codecs,
executable services for Large Language Models (LLMs), and structured data
schemas, along with classes for handling prompts and prompt scenarios.
"""
from simcore_ai_django.components import *

__all__ = [
    "DjangoBaseCodec",
    "DjangoExecutableLLMService", "DjangoBaseService",
    "DjangoBaseOutputSchema", "DjangoBaseOutputBlock", "DjangoBaseOutputItem",
    "Prompt", "PromptEngine", "PromptSection", "PromptScenario",
]
