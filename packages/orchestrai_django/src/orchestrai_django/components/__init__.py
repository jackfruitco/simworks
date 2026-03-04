"""
A module that provides foundational implementations for Django-based codecs,
schemas, services, and instruction utilities.

Available Classes:
- DjangoBaseCodec: Provides base functionality for handling codecs in Django-based systems.
- DjangoBaseOutputSchema: Defines the base schema for output data in Django applications.
- DjangoBaseOutputBlock: Represents a block of output data in Django schemas.
- DjangoBaseOutputItem: Represents an individual item in an output block.
- DjangoBaseService: Provides foundational service functionality in Django-based systems.

All exports are explicitly defined to ensure clarity regarding provided utilities.
"""
from .codecs import DjangoBaseCodec
from .schemas import DjangoBaseOutputSchema, DjangoBaseOutputBlock, DjangoBaseOutputItem
from .services import DjangoBaseService

__all__ = [
    "DjangoBaseCodec",
    "DjangoBaseService",
    "DjangoBaseOutputSchema", "DjangoBaseOutputBlock", "DjangoBaseOutputItem",
]
