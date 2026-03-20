"""Persist functions for chatlab schemas.

These functions handle complex transformations where Pydantic output items
do not map 1:1 to Django model fields (e.g., ResultMessageItem → Message
requires text extraction and FK lookups).
"""

from __future__ import annotations

import logging
from typing import Any

from orchestrai.types import ResultMessageItem
from orchestrai_django.persistence import PersistContext

logger = logging.getLogger(__name__)


def _extract_text(msg: ResultMessageItem) -> str:
    """Extract text content from a ResultMessageItem."""
    for content in msg.content:
        if hasattr(content, "type") and content.type in ("text", "output_text"):
            return content.text
    return ""


async def _resolve_conversation_id(ctx: PersistContext) -> int | None:
    """Resolve conversation_id from context, falling back to the patient conversation."""
    extra = ctx.extra or {}
    conversation_id = extra.get("conversation_id")
    if conversation_id:
        return conversation_id

    # Backward compat: find patient conversation for this simulation
    from apps.simcore.models import Conversation

    conv = await (
        Conversation.objects.filter(
            simulation_id=ctx.simulation_id,
            conversation_type__slug="simulated_patient",
        )
        .values_list("id", flat=True)
        .afirst()
    )
    return conv


async def persist_stitch_messages(messages: list[ResultMessageItem], ctx: PersistContext) -> list:
    """Persist ResultMessageItem list → chatlab.Message instances for Stitch.

    Same pattern as ``persist_messages`` but uses the Stitch bot user and
    requires ``conversation_id`` in context (no fallback to patient conversation).
    """
    from asgiref.sync import sync_to_async

    from apps.chatlab.models import Message, RoleChoices
    from apps.common.utils.accounts import get_system_user

    stitch_user = await sync_to_async(get_system_user)("Stitch")

    # Stitch messages must always target a specific conversation — don't silently
    # fall back to the patient conversation.
    extra = ctx.extra or {}
    conversation_id = extra.get("conversation_id")
    if not conversation_id:
        logger.error(
            "persist_stitch_messages called without conversation_id, sim=%s",
            ctx.simulation_id,
        )
        raise ValueError("conversation_id is required for Stitch message persistence")

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
            conversation_id=conversation_id,
            content=text,
            role=RoleChoices.ASSISTANT,
            is_from_ai=True,
            message_type="text",
            sender=stitch_user,
            display_name="Stitch",
            service_call_attempt=attempt_obj,
            provider_response_id=provider_response_id,
        )
        created.append(m)

    return created


async def persist_messages(messages: list[ResultMessageItem], ctx: PersistContext) -> list:
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
    conversation_id = await _resolve_conversation_id(ctx)

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
            conversation_id=conversation_id,
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


def _coerce_orm_value(value: Any) -> Any:
    """Coerce Pydantic values into Django-friendly primitives."""
    if hasattr(value, "value"):  # Enum
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


async def persist_metadata_upsert(metadata_items: list[Any], ctx: PersistContext) -> list:
    """Upsert metadata items by (simulation_id, key).

    Reply turns can emit incremental metadata updates. Since SimulationMetadata
    enforces unique (simulation, key), repeated keys are updated in-place.
    If an existing key belongs to a different polymorphic subtype, it is replaced.
    """
    from django.apps import apps as django_apps

    from apps.simcore.models import SimulationMetadata

    attempt_id = (ctx.extra or {}).get("service_call_attempt_id")
    persisted = []
    for item in metadata_items:
        model_ref = getattr(type(item), "__orm_model__", None)
        if not model_ref:
            raise ValueError(f"No __orm_model__ on metadata item type: {type(item).__name__}")
        model_cls = django_apps.get_model(*model_ref.split(".", 1))

        model_field_names = {f.name for f in model_cls._meta.get_fields() if hasattr(f, "column")}
        kwargs = {"simulation_id": ctx.simulation_id}
        for field_name in type(item).model_fields:
            if field_name == "kind":
                continue
            if field_name in model_field_names:
                kwargs[field_name] = _coerce_orm_value(getattr(item, field_name))
        if "service_call_attempt" in model_field_names and attempt_id:
            kwargs["service_call_attempt_id"] = attempt_id

        key = kwargs.get("key")
        if not key:
            raise ValueError(f"Metadata item missing key: {type(item).__name__}")

        existing = await SimulationMetadata.objects.filter(
            simulation_id=ctx.simulation_id,
            key=key,
        ).afirst()

        if existing is None:
            obj = await model_cls.objects.acreate(**kwargs)
            persisted.append(obj)
            continue

        existing_model_name = getattr(getattr(existing, "_meta", None), "model_name", None)
        target_model_name = getattr(getattr(model_cls, "_meta", None), "model_name", None)
        same_subtype = isinstance(existing, model_cls) or existing_model_name == target_model_name

        if same_subtype:
            update_fields = []
            for field_name, value in kwargs.items():
                if field_name == "simulation_id":
                    continue
                setattr(existing, field_name, value)
                update_fields.append(field_name)
            if update_fields:
                await existing.asave(update_fields=update_fields)
            persisted.append(existing)
            continue

        # Subtype changed for same key: replace row to keep polymorphic data aligned.
        await existing.adelete()
        obj = await model_cls.objects.acreate(**kwargs)
        persisted.append(obj)

    return persisted
