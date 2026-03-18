# simcore/orca/services/feedback.py
"""Feedback AI services for simulation using class-based instructions."""

import logging
from typing import ClassVar

from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca

from ..mixins import FeedbackMixin  # Identity mixin for component discovery

logger = logging.getLogger(__name__)


@orca.service
class GenerateInitialFeedback(FeedbackMixin, DjangoBaseService):
    """Generate the initial patient feedback using Pydantic AI."""

    instruction_refs: ClassVar[list[str]] = [
        "simcore.feedback.FeedbackInitialInstruction",
        "common.feedback.FeedbackEducatorInstruction",
        "common.shared.MedicalAccuracyInstruction",
    ]
    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from apps.simcore.orca.schemas import GenerateInitialSimulationFeedback as _Schema

    response_schema = _Schema


@orca.service
class GenerateFeedbackContinuationReply(FeedbackMixin, DjangoBaseService):
    """Generate continuation feedback using Pydantic AI."""

    instruction_refs: ClassVar[list[str]] = [
        "simcore.feedback.FeedbackContinuationInstruction",
        "common.feedback.FeedbackEducatorInstruction",
    ]
    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from apps.simcore.orca.schemas import GenerateFeedbackContinuationResponse as _Schema

    response_schema = _Schema
