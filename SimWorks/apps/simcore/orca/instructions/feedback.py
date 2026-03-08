"""Instruction classes for simulation feedback services."""

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca


@orca.instruction(order=0)
class FeedbackInitialInstruction(BaseInstruction):
    instruction = (
        "Evaluate the completed simulation and produce structured initial feedback.\n"
        "Assess diagnostic accuracy, treatment-plan appropriateness, patient experience (0-5), "
        "and a concise narrative debrief.\n"
        "The narrative should include: correct diagnosis and treatment plan, key differentials, "
        "important missed history questions (if any), 1-2 sustains, and 1-2 improves.\n\n"
        "### Response Schema\n"
        "- Use GenerateInitialSimulationFeedback.\n"
        "- Include top-level keys: metadata and llm_conditions_check.\n"
        "- metadata must match InitialFeedbackBlock.\n"
        "- llm_conditions_check must be a concise list of key/value checks."
    )


@orca.instruction(order=10)
class FeedbackContinuationInstruction(BaseInstruction):
    instruction = (
        "Provide a direct, concise answer to the learner's follow-up question.\n"
        "Keep coaching practical and tied to the completed simulation context.\n\n"
        "### Response Schema\n"
        "- Use GenerateFeedbackContinuationResponse.\n"
        "- Include top-level keys: metadata and llm_conditions_check.\n"
        "- metadata.direct_answer must contain the learner-facing answer text.\n"
        "- llm_conditions_check must be a concise list of key/value checks."
    )
