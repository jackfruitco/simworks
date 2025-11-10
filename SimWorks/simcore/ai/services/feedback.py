# simcore/ai/services/feedback.py
from simcore_ai_django.api.types import DjangoExecutableLLMService
from simcore_ai_django.api.decorators import ai_service
from ..mixins import FeedbackMixin

@ai_service
class GenerateHotwashInitialResponse(DjangoExecutableLLMService, FeedbackMixin):
    """Generate the initial patient feedback."""
    execution_mode = "async"


@ai_service
class GenerateHotwashContinuationResponse(DjangoExecutableLLMService, FeedbackMixin):
    """Generate the continuation feedback."""
    pass
