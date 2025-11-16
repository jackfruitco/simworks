# simcore/ai/schemas/feedback.py


from pydantic import Field

from simcore_ai_django.api.types import DjangoBaseOutputSchema
from simcore_ai_django.api import simcore
from .output_items import HotwashInitialBlock, LLMConditionsCheckItem


@simcore.schema
class HotwashInitialSchema(DjangoBaseOutputSchema):
    """Initial patient feedback."""
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(..., json_schema_extra={"kind": "conditions_check"})
    metadata: HotwashInitialBlock = Field(..., json_schema_extra={"kind": "feedback"})
