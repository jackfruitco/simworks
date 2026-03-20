"""Lab order results output schema for the GenerateLabResults service."""

import logging
from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from apps.simcore.orca.schemas.metadata_items import LabResultItem, RadResultItem
from apps.simcore.orca.schemas.output_items import LLMConditionsCheckItem

logger = logging.getLogger(__name__)

# Discriminated union restricted to lab and radiology results only.
# Lab orders cannot emit other metadata kinds (history, demographics, etc.).
LabOrRadItem = Annotated[
    LabResultItem | RadResultItem,
    Field(discriminator="kind"),
]
class LabOrderResultsOutputSchema(BaseModel):
    """Output schema for the GenerateLabResults service.

    The LLM returns one result item per ordered test.

    **Persistence** (declarative):
    - results → simcore.LabResult or simcore.RadResult via auto-mapper (__orm_model__)
    - llm_conditions_check → NOT PERSISTED

    **Durable Events**:
    - ChatLab emits outbox-backed events after generic domain persistence completes
    - ``simulation.metadata.results_created`` is the canonical metadata refresh event
    - ``metadata.created`` remains a temporary compatibility alias
    """

    model_config = ConfigDict(extra="forbid")

    results: list[LabOrRadItem] = Field(
        ...,
        min_length=1,
        description="Ordered test results — one item per ordered test",
    )
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        default_factory=list,
        description="Internal workflow compliance checks (not persisted)",
    )

    __persist__: ClassVar[dict] = {"results": None}  # auto-map via __orm_model__
    __persist_primary__ = "results"

    async def post_persist(self, results, context):
        """Reserved hook for persistence-only follow-ups."""
        return None
