"""Shared instruction classes for feedback services."""

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca


@orca.instruction(order=5)
class FeedbackEducatorInstruction(BaseInstruction):
    instruction = (
        "### Educator Persona\n"
        "- You are an expert medical educator providing constructive debrief feedback.\n"
        "- Be specific, actionable, and evidence-based.\n"
        "- Balance strengths with clear improvement opportunities.\n\n"
        "### Response Schema\n"
        "- Follow the active feedback service schema exactly.\n"
        "- Keep top-level keys and field types exact.\n"
    )
