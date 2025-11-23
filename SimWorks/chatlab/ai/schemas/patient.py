# simcore/ai/schemas/patient.py


from pydantic import Field

from simcore_ai_django.api import simcore
from simcore_ai_django.api.types import DjangoBaseOutputSchema, DjangoLLMResponseItem
from simulation.ai.mixins import StandardizedPatientMixin
from simulation.ai.schemas.output_items import LLMConditionsCheckItem
from ..mixins import ChatlabMixin


@simcore.schema
class PatientInitialOutputSchema(ChatlabMixin, StandardizedPatientMixin, DjangoBaseOutputSchema):
    """
    Output for the initial patient response turn.
    - `image_requested`: whether the assistant is asking to attach/generate an image
    - `messages`: assistant messages to render/send
    - `metadata`: additional assistant “side-channel” messages (structured or non-user-visible)
    - `llm_conditions_check`: simple flags for follow-on logic
    """
    messages: list[DjangoLLMResponseItem] = Field(..., min_length=1)
    metadata: list[DjangoLLMResponseItem] = Field(...)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)


@simcore.schema
class PatientReplyOutputSchema(ChatlabMixin, StandardizedPatientMixin, DjangoBaseOutputSchema):
    """Output for subsequent patient reply turns."""
    image_requested: bool
    messages: list[DjangoLLMResponseItem] = Field(..., min_length=1)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)


@simcore.schema
class PatientResultsOutputSchema(ChatlabMixin, StandardizedPatientMixin, DjangoBaseOutputSchema):
    """
    Final “results” payload for the interaction.
    `metadata` can include structured output (e.g., scored observations) as messages.
    """
    metadata: list[DjangoLLMResponseItem] = Field(...)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)
