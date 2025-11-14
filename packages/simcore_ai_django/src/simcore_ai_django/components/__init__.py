"""
A module that provides foundational implementations for Django-based codecs,
schemas, services, and prompt-related utilities.

This module includes essential components required for working with Django-based
applications, such as codecs for handling input and output, service utilities for
business logic, and prompt utilities for generating and managing interactive
scenarios. These components can be extended or used as-is to streamline specific
development workflows.

Available Classes:
- DjangoBaseCodec: Provides base functionality for handling codecs in Django-based systems.
- DjangoBaseOutputSchema: Defines the base schema for output data in Django applications.
- DjangoBaseOutputBlock: Represents a block of output data in Django schemas.
- DjangoBaseOutputItem: Represents an individual item in an output block.
- DjangoBaseService: Provides foundational service functionality in Django-based systems.
- DjangoExecutableLLMService: Extends DjangoBaseService for executing language model services.
- Prompt: Represents a generative or interactive prompt.
- PromptEngine: Manages prompt generation and rendering.
- PromptSection: Represents a section in a structured prompt.
- PromptScenario: Represents a complete scenario built from multiple prompts.

All exports are explicitly defined to ensure clarity regarding provided utilities.
"""
from .codecs import DjangoBaseCodec
from .schemas import DjangoBaseOutputSchema, DjangoBaseOutputBlock, DjangoBaseOutputItem
from .services import DjangoBaseService, DjangoExecutableLLMService
from .promptkit import Prompt, PromptEngine, PromptSection, PromptScenario

__all__ = [
    "DjangoBaseCodec",
    "DjangoExecutableLLMService", "DjangoBaseService",
    "DjangoBaseOutputSchema", "DjangoBaseOutputBlock", "DjangoBaseOutputItem",
    "Prompt", "PromptEngine", "PromptSection", "PromptScenario",
]
