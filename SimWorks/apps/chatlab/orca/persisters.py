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
    from apps.chatlab.models import Message, RoleChoices
    from apps.common.utils.accounts import aget_or_create_system_user
    from apps.simcore.models import Simulation

    system_user = await aget_or_create_system_user()
    sim = await Simulation.objects.aget(id=ctx.simulation_id)
    display_name = sim.sim_patient_display_name or "AI"

    created = []
    attempt_obj = None
    provider_response_id = None
    extra = ctx.extra or {}
    attempt_id = extra.get("service_call_attempt_id")
    if attempt_id:
        try:
            from orchestrai_django.models import ServiceCallAttempt
            attempt_obj = await ServiceCallAttempt.objects.aget(pk=attempt_id)
        except Exception as exc:
            logger.warning("Failed to load ServiceCallAttempt %s: %s", attempt_id, exc)
    provider_response_id = extra.get("provider_response_id")
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
            service_call_attempt=attempt_obj,
            provider_response_id=provider_response_id,
        )
        created.append(m)

    return created


