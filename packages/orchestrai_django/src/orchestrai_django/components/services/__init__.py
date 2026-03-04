# orchestrai_django/components/services/__init__.py
from .mixins import PreviousResponseMixin
from .services import DjangoBaseService

# Backward compatibility alias - DjangoPydanticAIService is now DjangoBaseService
DjangoPydanticAIService = DjangoBaseService

__all__ = [
    "DjangoBaseService",
    "DjangoPydanticAIService",  # Alias for backward compatibility
    "PreviousResponseMixin",
]
