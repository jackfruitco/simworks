# simcore/ai_v1/schemas/output.py
from __future__ import annotations

from pydantic import Field

from chatlab.ai.schemas.output_schema import LLMConditionsCheckItem
from simcore.ai_v1.schemas import StrictOutputSchema
from simcore.ai_v1.schemas.output_types import OutputFeedbackEndexItem, OutputMessageItem


class OutputFeedbackSchema(StrictOutputSchema):
    """Feedback schema for output."""
    metadata: list[OutputFeedbackEndexItem] = Field(...)


class InstructorReplyOutputSchema(StrictOutputSchema):
    """Instructor reply schema for output.

    Currently, this schema is only used for the `instructor_reply` tool.
    """
    messages: list[OutputMessageItem] = Field(...)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)