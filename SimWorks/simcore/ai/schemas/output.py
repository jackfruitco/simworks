# simcore/ai/schemas/output.py
from __future__ import annotations

from pydantic import Field

from simcore.ai.schemas import StrictOutputSchema
from simcore.ai.schemas.output_types import OutputFeedbackEndexItem


class OutputFeedbackSchema(StrictOutputSchema):
    """Feedback schema for output."""
    metadata: list[OutputFeedbackEndexItem] = Field(...)