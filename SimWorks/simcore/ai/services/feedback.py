# simcore/ai/services/feedback.py
from simcore_ai_django.services import DjangoExecutableLLMService


class GenerateHotwashInitialResponse(DjangoExecutableLLMService):
    """Generate the initial patient feedback."""
    raise NotImplementedError


class GenerateHotwashContinuationResponse(DjangoExecutableLLMService):
    """Generate the continuation feedback."""
    raise NotImplementedError
