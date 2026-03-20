# chatlab/orca/schemas/stitch.py
"""
Stitch facilitator output schema for Pydantic AI.

Stitch responses are simpler than patient responses — just messages,
no metadata or conditions checks.
"""

from pydantic import BaseModel, ConfigDict, Field

from apps.chatlab.orca.persisters import persist_stitch_messages
from orchestrai.types import ResultMessageItem


class StitchReplyOutputSchema(BaseModel):
    """Output for Stitch facilitator reply turns.

    **Persistence** (declarative):
    - messages → chatlab.Message via ``persist_stitch_messages``

    **Durable Events**:
    - ChatLab emits outbox-backed message events after generic domain persistence completes
    """

    model_config = ConfigDict(extra="forbid")

    messages: list[ResultMessageItem] = Field(
        ...,
        min_length=1,
        description="Response messages from Stitch facilitator",
    )

    __persist__ = {"messages": persist_stitch_messages}
    __persist_primary__ = "messages"

    async def post_persist(self, results, context):
        """Reserved hook for persistence-only follow-ups."""
        return None
