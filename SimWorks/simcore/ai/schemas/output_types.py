# simcore/ai/schemas/output_types.py
from __future__ import annotations

from typing import Annotated, Union, Literal

from pydantic import Field

from .base import StrictBaseModel, project_from
from .types import (
    MessageItem,
    # Metafield DTOs:
    GenericMetafield,
    LabResultMetafield,
    RadResultMetafield,
    PatientHistoryMetafield,
    SimulationFeedbackMetafield,
    PatientDemographicsMetafield,
    SimulationMetafield,
    ScenarioMetafield,
)

# Messages: only expose what the LLM should output
OutputMessageItem = project_from(
    MessageItem,
    include=("role", "content"),
    overrides={"role": Literal["patient"]},   # narrow if appropriate for this schema
    name="OutputMessageItem",
)

# Metafields: expose only LLM-facing fields (drop db_pk, etc.)
OutputGenericMetafield = project_from(
    GenericMetafield,
    exclude=("db_pk", "extra"),                # keep extra if you want; default here hides it
    name="OutputGenericMetafield",
)

OutputLabResultMetafield = project_from(
    LabResultMetafield,
    include=(
        "kind",
        "key",
        "panel_name",
        "result_name",
        "result_value",
        "result_unit",
        "reference_range_low",
        "reference_range_high",
        "result_flag",
        "result_comment",
    ),
    name="OutputLabResultMetafield",
)

OutputRadResultMetafield = project_from(
    RadResultMetafield,
    include=("kind", "key", "value", "flag"),
    name="OutputRadResultMetafield",
)

OutputPatientHistoryMetafield = project_from(
    PatientHistoryMetafield,
    include=("kind", "key", "value", "is_resolved", "duration"),
    name="OutputPatientHistoryMetafield",
)

OutputSimulationFeedbackMetafield = project_from(
    SimulationFeedbackMetafield,
    include=("kind", "key", "value"),
    name="OutputSimulationFeedbackMetafield",
)

OutputPatientDemographicsMetafield = project_from(
    PatientDemographicsMetafield,
    include=("kind", "key", "value"),
    name="OutputPatientDemographicsMetafield",
)

OutputSimulationMetafield = project_from(
    SimulationMetafield,
    include=("kind", "key", "value"),
    name="OutputSimulationMetafield",
)

OutputScenarioMetafield = project_from(
    ScenarioMetafield,
    include=("kind", "key", "value"),
    name="OutputScenarioMetafield",
)

OutputMetafieldItem = Annotated[
    Union[
        OutputGenericMetafield,
        OutputLabResultMetafield,
        OutputRadResultMetafield,
        OutputPatientHistoryMetafield,
        OutputSimulationFeedbackMetafield,
        OutputPatientDemographicsMetafield,
        OutputSimulationMetafield,
        OutputScenarioMetafield,
    ],
    Field(discriminator="kind"),
]