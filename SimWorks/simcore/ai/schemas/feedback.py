# simcore/ai/schemas/feedback.py
from __future__ import annotations

from simcore_ai_django.api.types import DjangoBaseOutputSchema

from .output_items import HotwashInitialBlock, LLMConditionsCheckItem


from pydantic import Field

class HotwashInitialSchema(DjangoBaseOutputSchema):
    """Initial patient feedback."""
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(..., json_schema_extra={"kind": "conditions_check"})
    metadata: HotwashInitialBlock = Field(..., json_schema_extra={"kind": "feedback"})