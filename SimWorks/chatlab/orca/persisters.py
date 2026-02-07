"""Persist functions for chatlab schemas.

These functions handle complex transformations where Pydantic output items
do not map 1:1 to Django model fields (e.g., ResultMessageItem → Message
requires text extraction and FK lookups).
"""

from __future__ import annotations

import logging

from orchestrai.types import ResultMessageItem
from orchestrai_django.persistence import PersistContext

logger = logging.getLogger(__name__)


def _extract_text(msg: ResultMessageItem) -> str:
    """Extract text content from a ResultMessageItem."""
    for content in msg.content:
        if hasattr(content, "type") and content.type in ("text", "output_text"):
            return content.text
    return ""


async def persist_messages(
    messages: list[ResultMessageItem], ctx: PersistContext
) -> list:
    """Persist ResultMessageItem list → chatlab.Message instances.

    This is an explicit persist function because ResultMessageItem has a
    different structure from Message (content is a list of content blocks,
    needs text extraction, FK lookups for sender, etc.).
    """
    from chatlab.models import Message, RoleChoices
    from core.utils.accounts import aget_or_create_system_user
    from simulation.models import Simulation

    system_user = await aget_or_create_system_user()
    sim = await Simulation.objects.aget(id=ctx.simulation_id)
    display_name = sim.sim_patient_display_name or "AI"

    created = []
    for msg in messages:
        text = _extract_text(msg)
        if not text:
            continue

        m = await Message.objects.acreate(
            simulation_id=ctx.simulation_id,
            content=text,
            role=RoleChoices.ASSISTANT,
            is_from_ai=True,
            message_type="text",
            sender=system_user,
            display_name=display_name,
        )
        created.append(m)

    return created


async def persist_results_metadata(
    metadata: list[ResultMessageItem], ctx: PersistContext
) -> list:
    """Persist ResultMessageItem list → SimulationMetadata instances.

    Used by PatientResultsOutputSchema where metadata items are
    ResultMessageItem (not ResultMetafield) — they carry key/value
    in item_meta and text in content blocks.
    """
    from simulation.models import SimulationMetadata

    created = []
    for meta_item in metadata:
        try:
            text = _extract_text(meta_item)

            key = "result"
            for metafield in meta_item.item_meta:
                if metafield.key == "key":
                    key = str(metafield.value) if metafield.value else "result"
                    break

            obj = await SimulationMetadata.objects.acreate(
                simulation_id=ctx.simulation_id,
                key=key,
                value=text,
            )
            created.append(obj)
        except Exception as exc:
            logger.warning("Failed to persist results metadata item: %s", exc, exc_info=True)

    return created
