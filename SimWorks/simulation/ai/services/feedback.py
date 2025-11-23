# simcore/ai/services/feedback.py
from simcore_ai_django.api.types import DjangoBaseService
from simcore_ai_django.api import simcore
from ..mixins import FeedbackMixin

@simcore.service
class GenerateHotwashInitialResponse(FeedbackMixin, DjangoBaseService):
    """Generate the initial patient feedback."""


@simcore.service
class GenerateHotwashContinuationResponse(FeedbackMixin, DjangoBaseService):
    """Generate the continuation feedback."""
    pass
