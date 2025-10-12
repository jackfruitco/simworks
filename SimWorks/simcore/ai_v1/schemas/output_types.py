# simcore/ai_v1/schemas/output_types.py
from __future__ import annotations

from typing import Annotated, Union, Literal, TypeAlias

from pydantic import Field

from .base import StrictBaseModel, project_from
from .types import (
    MessageItem,
    # Metafield DTOs:
    GenericMetafield,
    LabResultMetafield,
    RadResultMetafield,
    PatientHistoryMetafield,
    PatientDemographicsMetafield,
    SimulationMetafield,
    ScenarioMetafield,
    CorrectDiagnosisFeedback,
    CorrectTreatmentPlanFeedback,
    PatientExperienceFeedback, OverallFeedbackMetafield,
)

# Messages: only expose what the LLM should output
OutputMessageItem: type[StrictBaseModel] = project_from(
    MessageItem,
    include=("role", "content"),
    overrides={"role": Literal["patient", "instructor"]},
    name="OutputMessageItem",
)

# Metadata: expose only LLM-facing fields (drop db_pk, etc.)
OutputGenericMetafield: type[StrictBaseModel] = project_from(
    GenericMetafield,
    include=("kind", "key", "value"),
    name="OutputGenericMetafield",
)

OutputLabResultMetafield: type[StrictBaseModel] = project_from(
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

OutputRadResultMetafield: type[StrictBaseModel] = project_from(
    RadResultMetafield,
    include=("kind", "key", "value", "flag"),
    name="OutputRadResultMetafield",
)

OutputPatientHistoryMetafield: type[StrictBaseModel] = project_from(
    PatientHistoryMetafield,
    include=("kind", "key", "value", "is_resolved", "duration"),
    name="OutputPatientHistoryMetafield",
)

OutputPatientDemographicsMetafield: type[StrictBaseModel] = project_from(
    PatientDemographicsMetafield,
    include=("kind", "key", "value"),
    name="OutputPatientDemographicsMetafield",
)

OutputSimulationMetafield: type[StrictBaseModel] = project_from(
    SimulationMetafield,
    include=("kind", "key", "value"),
    name="OutputSimulationMetafield",
)

OutputScenarioMetafield: type[StrictBaseModel] = project_from(
    ScenarioMetafield,
    include=("kind", "key", "value"),
    name="OutputScenarioMetafield",
)

OutputMetafieldItem: TypeAlias = Annotated[
    # TODO: consider renaming for clarity.
    Union[
        # OutputGenericMetafield,
        OutputPatientHistoryMetafield,
        # OutputSimulationFeedbackMetafield,
        OutputPatientDemographicsMetafield,
        OutputSimulationMetafield,
        OutputScenarioMetafield,
    ],
    Field(discriminator="kind"),
]

OutputCorrectDiagnosisFeedback: type[StrictBaseModel] = project_from(
    CorrectDiagnosisFeedback,
    include=("kind", "key", "value"),
    name="OutputCorrectDiagnosisFeedbackMetafield",
)

OutputCorrectTreatmentPlanFeedback: type[StrictBaseModel] = project_from(
    CorrectTreatmentPlanFeedback,
    include=("kind", "key", "value"),
    name="OutputCorrectTreatmentPlanFeedbackMetafield",
)

OutputPatientExperienceFeedback: type[StrictBaseModel] = project_from(
    PatientExperienceFeedback,
    include=("kind", "key", "value"),
    name="OutputPatientExperienceMetafield",
)

OutputOverallFeedback: type[StrictBaseModel] = project_from(
    OverallFeedbackMetafield,
    include=("kind", "key", "value"),
    name="OutputOverallFeedbackMetafield",
)

OutputFeedbackEndexItem: TypeAlias = Annotated[
    Union[
        OutputCorrectDiagnosisFeedback,
        OutputCorrectTreatmentPlanFeedback,
        OutputPatientExperienceFeedback,
        OutputOverallFeedback,
    ],
    Field(discriminator="kind"),
]

OutputResultItem: TypeAlias = Annotated[
    Union[
        OutputLabResultMetafield,
        OutputRadResultMetafield,
    ],
    Field(discriminator="kind"),
]

FullOutputMetafieldItem: TypeAlias = Annotated[
    # all OutputMetafieldItem fields must be added here for slim validation in `adapt_response`
    Union[
        OutputGenericMetafield,
        OutputPatientHistoryMetafield,
        OutputPatientDemographicsMetafield,
        OutputSimulationMetafield,
        OutputScenarioMetafield,
        OutputLabResultMetafield,
        OutputRadResultMetafield,
        OutputFeedbackEndexItem,
    ],
    Field(discriminator="kind"),
]