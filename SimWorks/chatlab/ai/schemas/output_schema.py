from __future__ import annotations

from typing import Any, get_args, get_origin

from pydantic import Field, create_model

from simcore.ai.schemas import (
    StrictOutputSchema,
    Boolish,
    OutputMessageItem,
    OutputMetafieldItem,
)
from simcore.ai.schemas.output_types import OutputResultItem


class LLMConditionsCheckItem(StrictOutputSchema):
    key: str
    value: str


class PatientInitialOutputSchema(StrictOutputSchema):
    image_requested: bool
    messages: list[OutputMessageItem] = Field(...)
    metadata: list[OutputMetafieldItem] = Field(...)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)


class PatientReplyOutputSchema(StrictOutputSchema):
    image_requested: bool = Field(...)
    messages: list[OutputMessageItem] = Field(...)
    # metadata: list[OutputMetafieldItem] = Field(default_factory=list)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)


class PatientResultsOutputSchema(StrictOutputSchema):
    metadata: list[OutputResultItem] = Field(...)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)
