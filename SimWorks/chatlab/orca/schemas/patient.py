# chatlab/orca/schemas/patient.py
"""
Patient output schemas for Pydantic AI.

These are plain Pydantic models used as result_type for Pydantic AI agents.
Pydantic AI handles validation natively - no @schema decorator needed.
"""

import logging

from pydantic import BaseModel, Field, ConfigDict

from orchestrai.types import ResultMessageItem, ResultMetafield
from simulation.orca.schemas.output_items import LLMConditionsCheckItem
from chatlab.orca.persisters import persist_results_metadata
from .mixins import PatientResponseBaseMixin

logger = logging.getLogger(__name__)


class PatientInitialOutputSchema(PatientResponseBaseMixin):
    """Output for the initial patient response turn.

    **Persistence** (declarative):
    - messages → chatlab.Message via ``persist_messages`` (inherited from mixin)
    - metadata → simulation.SimulationMetadata via auto-mapper (``__orm_model__``)
    - llm_conditions_check → NOT PERSISTED
    """

    metadata: list[ResultMetafield] = Field(
        ...,
        description="Patient demographics and initial metadata"
    )

    __persist__ = {"metadata": None}  # None = auto-map via ResultMetafield.__orm_model__
    __persist_primary__ = "messages"


class PatientReplyOutputSchema(PatientResponseBaseMixin):
    """Output for subsequent patient reply turns.

    **Persistence** (declarative):
    - messages → chatlab.Message via ``persist_messages`` (inherited from mixin)
    - image_requested → NOT PERSISTED (handled via ``post_persist`` hook)
    - llm_conditions_check → NOT PERSISTED
    """

    image_requested: bool = Field(
        ...,
        description="Whether the response references images/scans"
    )

    __persist_primary__ = "messages"

    async def post_persist(self, results, context):
        if self.image_requested:
            logger.info("Image requested for simulation %s", context.simulation_id)


class PatientResultsOutputSchema(BaseModel):
    """Final results payload — scored observations and assessments.

    Does NOT inherit PatientResponseBaseMixin (no user-facing messages).

    **Persistence** (declarative):
    - metadata → simulation.SimulationMetadata via ``persist_results_metadata``
    - llm_conditions_check → NOT PERSISTED
    """

    model_config = ConfigDict(extra="forbid")

    metadata: list[ResultMessageItem] = Field(
        ...,
        description="Scored observations and final assessment"
    )
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        ...,
        description="Completion and workflow flags"
    )

    __persist__ = {"metadata": persist_results_metadata}
    __persist_primary__ = "metadata"
