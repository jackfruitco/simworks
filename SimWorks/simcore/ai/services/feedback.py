# simcore/ai/services/feedback.py
from simcore_ai_django.services import DjangoExecutableLLMService


class FeedbackMixin:
    bucket = "feedback"


class GenerateHotwashInitialResponse(DjangoExecutableLLMService, FeedbackMixin):
    """Generate the initial patient feedback."""
    execution_mode = "async"



class GenerateHotwashContinuationResponse(DjangoExecutableLLMService, FeedbackMixin):
    """Generate the continuation feedback."""
    raise NotImplementedError
