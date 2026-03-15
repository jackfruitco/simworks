"""Lab order results output schema for the GenerateLabResults service."""

import logging
from typing import Annotated, ClassVar, Literal

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


def _metadata_kind(meta) -> str:
    model_name = getattr(getattr(meta, "_meta", None), "model_name", "") or ""
    kind_by_model = {
        "labresult": "lab_result",
        "radresult": "rad_result",
    }
    if model_name in kind_by_model:
        return kind_by_model[model_name]
    return getattr(meta, "kind", "lab_result")


class LabOrderResultsOutputSchema(BaseModel):
    """Output schema for the GenerateLabResults service.

    The LLM returns one result item per ordered test.

    **Persistence** (declarative):
    - results → simcore.LabResult or simcore.RadResult via auto-mapper (__orm_model__)
    - llm_conditions_check → NOT PERSISTED

    **WebSocket Broadcasting**:
    - Broadcasts ``metadata.created`` events for each persisted result
    - Enables real-time UI updates as lab results arrive
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
        """Broadcast metadata.created events for each persisted lab/rad result."""
        from apps.common.outbox.helpers import broadcast_domain_objects

        persisted = results.get("results", [])
        if persisted:
            await broadcast_domain_objects(
                event_type="metadata.created",
                objects=persisted,
                context=context,
                payload_builder=lambda meta: {
                    "metadata_id": meta.id,
                    "kind": _metadata_kind(meta),
                    "key": meta.key,
                    "value": meta.value,
                },
            )
