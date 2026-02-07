# simulation/orca/schemas/feedback.py
"""
Feedback schemas for Pydantic AI.

These are plain Pydantic models used as result_type for Pydantic AI agents.
Pydantic AI handles validation natively - no @schema decorator needed.
"""

from pydantic import BaseModel, Field, ConfigDict

from simulation.orca.persist.feedback_block import persist_feedback_block
from .output_items import HotwashInitialBlock, LLMConditionsCheckItem


class HotwashInitialSchema(BaseModel):
    """Initial patient feedback (hotwash) schema.

    **Persistence** (declarative):
    - metadata → multiple SimulationFeedback records via ``persist_feedback_block``
    - llm_conditions_check → NOT PERSISTED
    """

    model_config = ConfigDict(extra="forbid")

    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        ...,
        description="Internal workflow conditions"
    )
    metadata: HotwashInitialBlock = Field(
        ...,
        description="Feedback data block"
    )

    __persist__ = {"metadata": persist_feedback_block}
    __persist_primary__ = "metadata"
