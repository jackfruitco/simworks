# simcore/ai/services/feedback.py
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import service
from ..mixins import FeedbackMixin

@service
class GenerateHotwashInitialResponse(FeedbackMixin, DjangoBaseService):
    """Generate the initial patient feedback."""


@service
class GenerateHotwashContinuationResponse(FeedbackMixin, DjangoBaseService):
    """Generate the continuation feedback."""
    pass
