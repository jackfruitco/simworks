# simulation/orca/services/feedback.py
"""
Feedback AI Services for Simulation using Pydantic AI.

WORKFLOW DIAGRAM
================

    GenerateInitialFeedback / GenerateFeedbackContinuationReply
      -> @system_prompt methods compose system prompt
      -> Pydantic AI Agent.run() with result_type
      -> Pydantic AI validates response automatically
      -> store RunResult to ServiceCall (JSON)
      -> [async] drain worker calls persistence handler
      -> persistence handler: ensure_idempotent() -> model_validate() -> ORM creates
      -> return RunResult (contains validated output as Pydantic model)

COERCION BOUNDARY
=================
Provider response -> Pydantic AI validation -> strict Pydantic model (result.output)

PERSISTENCE CONTRACT
====================
- Persistence handlers receive: RunResult with output (validated Pydantic model)
- Creates: SimulationFeedback rows
- Idempotency: PersistedChunk with (call_id, schema_identity) unique constraint
"""

import logging
from typing import ClassVar

from apps.common.orca.prompts import FeedbackEducatorMixin, MedicalAccuracyMixin
from orchestrai.prompts import system_prompt
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import service
from ..mixins import FeedbackMixin  # Identity mixin for component discovery

logger = logging.getLogger(__name__)


@service
class GenerateInitialFeedback(
    FeedbackEducatorMixin,
    MedicalAccuracyMixin,
    FeedbackMixin,  # Identity mixin
    DjangoBaseService,
):
    """
    Generate the initial patient feedback using Pydantic AI.

    This service analyzes a simulation session and generates feedback
    about the student's performance including diagnosis accuracy,
    treatment plan appropriateness, and patient experience rating.

    Inherited prompts (by weight):
    - FeedbackEducatorMixin (weight=95): Medical educator persona
    - MedicalAccuracyMixin (weight=85): Clinical accuracy enforcement
    """

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from apps.simcore.orca.schemas import GenerateInitialSimulationFeedback as _Schema
    response_schema = _Schema

    @system_prompt(weight=100)
    def feedback_instructions(self) -> str:
        """Instructions for generating initial feedback."""
        return (
            "You are an expert medical educator analyzing a student's performance "
            "in a simulated patient encounter.\n\n"
            "Based on the conversation history, evaluate:\n"        
            "1. Whether the student arrived at the correct diagnosis\n"
            "2. Whether the treatment plan was appropriate\n"
            "3. The quality of the patient experience (0-5 scale)\n"
            "4. Overall feedback and areas for improvement.\n"
            "Overall feedback should include:"
            "- correct final diagnosis and treatment plan"
            "- other diagnoses to consider as a differential"
            "- additional history taking questions not asked, if any"
            "- 1-2 sustains for the user"
            "- 1-2 improves for the user"
            "\n\n"
            "Begin by outputting a conditions check list under 'llm_conditions_check' "
            "to ensure you've considered all evaluation criteria before providing feedback."
            "The conditions check should include things like 'Did the user identify the diagnosis?', etc."
        )


@service
class GenerateFeedbackContinuationReply(
    FeedbackEducatorMixin,
    FeedbackMixin,  # Identity mixin
    DjangoBaseService,
):
    """
    Generate continuation feedback using Pydantic AI.

    This service generates follow-up feedback based on additional context
    or specific questions from the student.

    Inherited prompts (by weight):
    - FeedbackEducatorMixin (weight=95): Medical educator persona
    """

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    @system_prompt(weight=100)
    def continuation_instructions(self) -> str:
        """Instructions for continuation feedback."""
        return (
            "Continue providing feedback on the student's performance. "
            "Address any specific questions or areas they want to discuss. "
            "Maintain the same educational tone and provide constructive guidance."
        )
