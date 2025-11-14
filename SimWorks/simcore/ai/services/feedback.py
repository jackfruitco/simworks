# simcore/ai/services/feedback.py
from simcore_ai_django.api.types import DjangoBaseService
from simcore_ai_django.api.decorators import ai_service
from ..mixins import FeedbackMixin

@ai_service
class GenerateHotwashInitialResponse(DjangoBaseService, FeedbackMixin):
    """Generate the initial patient feedback."""
    execution_mode = "async"


@ai_service
class GenerateHotwashContinuationResponse(DjangoBaseService, FeedbackMixin):
    """Generate the continuation feedback."""
    pass
