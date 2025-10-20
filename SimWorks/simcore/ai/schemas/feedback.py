# simcore/ai/schemas/feedback.py
from __future__ import annotations

from pydantic import Field

from simcore_ai_django.api.types import DjangoBaseOutputSchema
from simcore_ai_django.schemas.decorators import response_schema
from .output_items import HotwashInitialBlock, LLMConditionsCheckItem


@response_schema
class HotwashInitialSchema(DjangoBaseOutputSchema):
    """Initial patient feedback."""
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(..., json_schema_extra={"kind": "conditions_check"})
    metadata: HotwashInitialBlock = Field(..., json_schema_extra={"kind": "feedback"})
