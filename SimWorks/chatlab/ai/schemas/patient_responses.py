from __future__ import annotations
from pydantic import Field
from simcore_ai_django.types import StrictOutputSchema, DjangoLLMResponseItem


class LLMConditionsCheckItem(StrictOutputSchema):
    """Key/value pair that signals whether a downstream condition is met."""
    key: str
    value: str


class PatientInitialOutputSchema(StrictOutputSchema):
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


class PatientReplyOutputSchema(StrictOutputSchema):
    """Output for subsequent patient reply turns."""
    image_requested: bool
    messages: list[DjangoLLMResponseItem] = Field(..., min_items=1)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)


class PatientResultsOutputSchema(StrictOutputSchema):
    """
    Final “results” payload for the interaction.
    `metadata` can include structured outputs (e.g., scored observations) as messages.
    """
    metadata: list[DjangoLLMResponseItem] = Field(...)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)