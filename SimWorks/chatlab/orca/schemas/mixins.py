"""Schema mixins for reusable field patterns.

Mixins provide common field structures that can be shared across multiple
schemas, reducing duplication and ensuring consistency.
"""

from pydantic import Field, BaseModel
from orchestrai_django.types import DjangoOutputItem
from simulation.orca.schemas.output_items import LLMConditionsCheckItem


class PatientResponseBaseMixin(BaseModel):
    """
    Common fields for all patient response schemas.

    **Purpose**: Extracts repeated field patterns across patient interaction schemas
    to reduce duplication and ensure consistency.

    **Provides**:
    - `messages`: list[DjangoOutputItem] (min 1) - The actual response content from
      the simulated patient. Always persisted to chatlab.Message.
    - `llm_conditions_check`: list[LLMConditionsCheckItem] (optional) - Internal
      flags for workflow logic. NOT persisted to database.

    **Usage Pattern**:
        @schema
        class MyPatientSchema(
            PatientResponseBaseMixin,  # Inherit common fields
            ChatlabMixin,
            DjangoBaseOutputSchema
        ):
            # Add schema-specific fields here
            metadata: list[DjangoOutputItem] = Field(...)

    **Schemas Using This Mixin**:
    - PatientInitialOutputSchema (initial patient turn)
    - PatientReplyOutputSchema (follow-up patient turns)

    **Note**: PatientResultsOutputSchema does NOT use this mixin because it contains
    no user-facing messages (only metadata/scoring).
    """

    messages: list[DjangoOutputItem] = Field(
        ...,
        min_length=1,
        description="Response messages from the simulated patient"
    )

    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        default_factory=list,
        description="Internal workflow conditions (not persisted to database)"
    )
