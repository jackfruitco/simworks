"""Schema mixins for reusable field patterns.

Mixins provide common field structures that can be shared across multiple
schemas, reducing duplication and ensuring consistency.

These are plain Pydantic models for use with Pydantic AI.
"""

from pydantic import BaseModel, Field, ConfigDict

from orchestrai.types import ResultMessageItem
from apps.simcore.orca.schemas.output_items import LLMConditionsCheckItem
from apps.chatlab.orca.persisters import persist_messages


class PatientResponseBaseMixin(BaseModel):
    """Base mixin with strict mode for Pydantic AI schemas.

    Common fields for all patient response schemas.

    **Provides**:
    - ``messages``: Persisted to chatlab.Message via ``persist_messages``.
    - ``llm_conditions_check``: NOT persisted (omitted from ``__persist__``).

    **Schemas Using This Mixin**:
    - PatientInitialOutputSchema (initial patient turn)
    - PatientReplyOutputSchema (follow-up patient turns)

    **Note**: PatientResultsOutputSchema does NOT use this mixin because it
    contains no user-facing messages (only metadata/scoring).
    """

    model_config = ConfigDict(extra="forbid")

    messages: list[ResultMessageItem] = Field(
        ...,
        min_length=1,
        description="Response messages from the simulated patient"
    )
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        ...,
        description="Internal workflow conditions"
    )

    __persist__ = {"messages": persist_messages}
