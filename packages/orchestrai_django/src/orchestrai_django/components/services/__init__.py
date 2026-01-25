# orchestrai_django/components/services/__init__.py
from .services import DjangoBaseService
from .mixins import PreviousResponseMixin

# Backward compatibility alias - DjangoPydanticAIService is now DjangoBaseService
DjangoPydanticAIService = DjangoBaseService

__all__ = [
    "DjangoBaseService",
    "DjangoPydanticAIService",  # Alias for backward compatibility
    "PreviousResponseMixin",
]
