# simcore/ai/services/feedback.py
from simcore_ai_django.api.types import DjangoExecutableLLMService
from ..mixins import FeedbackMixin


class GenerateHotwashInitialResponse(DjangoExecutableLLMService, FeedbackMixin):
    """Generate the initial patient feedback."""
    execution_mode = "async"



class GenerateHotwashContinuationResponse(DjangoExecutableLLMService, FeedbackMixin):
    """Generate the continuation feedback."""
    pass
