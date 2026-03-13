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

    **WebSocket Broadcasting**:
    - Broadcasts ``chat.message_created`` events for Stitch messages
    - Enables real-time UI updates when Stitch responds
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
        """Broadcast Stitch message creation to WebSocket clients."""
        from apps.chatlab.media_payloads import build_chat_message_event_payload
        from apps.common.outbox.helpers import broadcast_domain_objects

        messages = results.get("messages", [])
        if messages:
            await broadcast_domain_objects(
                event_type="chat.message_created",
                objects=messages,
                context=context,
                payload_builder=lambda msg: build_chat_message_event_payload(
                    msg,
                    fallback_conversation_type="simulated_feedback",
                    status="completed",
                ),
            )
