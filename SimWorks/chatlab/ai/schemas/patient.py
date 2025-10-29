# simcore/ai/schemas/patient.py
from __future__ import annotations

from pydantic import Field

from chatlab.ai.mixins import ChatlabMixin
from simcore.ai.mixins import StandardizedPatientMixin
from simcore_ai_django.api.types import DjangoBaseOutputSchema, DjangoLLMResponseItem, DjangoBaseOutputBlock
from simcore_ai_django.api.decorators import response_schema
from simcore.ai.schemas.output_items import LLMConditionsCheckItem


@response_schema
class PatientInitialOutputSchema(ChatlabMixin, StandardizedPatientMixin, DjangoBaseOutputSchema):
    """
    Output for the initial patient response turn.
    - `image_requested`: whether the assistant is asking to attach/generate an image
    - `messages`: assistant messages to render/send
    - `metadata`: additional assistant “side-channel” messages (structured or non-user-visible)
    - `llm_conditions_check`: simple flags for follow-on logic
    """
    messages: list[DjangoLLMResponseItem] = Field(..., min_items=1)
    metadata: list[DjangoLLMResponseItem] = Field(...)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)


@response_schema
class PatientReplyOutputSchema(ChatlabMixin, StandardizedPatientMixin, DjangoBaseOutputSchema):
    """Output for subsequent patient reply turns."""
    image_requested: bool
    messages: list[DjangoLLMResponseItem] = Field(..., min_items=1)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)


@response_schema
class PatientResultsOutputSchema(ChatlabMixin, StandardizedPatientMixin, DjangoBaseOutputSchema):
    """
    Final “results” payload for the interaction.
    `metadata` can include structured outputs (e.g., scored observations) as messages.
    """
    metadata: list[DjangoLLMResponseItem] = Field(...)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)
