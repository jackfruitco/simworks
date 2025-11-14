# config/ai/codecs.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Callable, ClassVar

from django.contrib.auth import get_user_model
from django.db import transaction

from chatlab.models import Message, RoleChoices
from simcore.models import Simulation, AIResponse
from simcore_ai_django.components.codecs.base import DjangoBaseCodec


class _MessageTextProvider(Protocol):
    def __call__(self, parsed: Any) -> str: ...


def default_first_message_text(parsed: Any) -> str:
    msgs = getattr(parsed, "messages", None) or []
    if not msgs:
        return ""
    first = msgs[0]
    return (first or {}).get("content", "") if isinstance(first, dict) else getattr(first, "content", "") or ""


@dataclass(eq=False)
class SimWorksCodec(DjangoBaseCodec):
    """
    Project-level base codec: template method that implements the shared ChatLab
    persistence flow. Subclasses usually just set maps/defaults; if they override
    `apersist`, they should `await super().apersist(...)` and add extras.
    """

    # If you want these configurable per-instance, keep them as dataclass fields.
    # If they’re global constants per-class, make them ClassVar[...] instead.
    create_assistant_message: bool = True
    message_text_provider: Callable[[Any], str] = field(
        default=default_first_message_text, repr=False
    )

    # Optional hook: allow dynamic defaults at runtime (e.g., inject FK/flags)
    def make_section_defaults(self, *, sim, sender, ai_resp) -> dict[str, dict | Callable]:
        # Fallback to any class-level `section_defaults` already set on the codec
        return getattr(self, "section_defaults", {})  # type: ignore[attr-defined]

    async def _aresolve_sim(self, sim_id: int) -> Simulation:
        return await Simulation.aresolve(sim_id)

    async def _aget_sender(self, sender_id: Optional[int], *, sim: Simulation):
        if not sender_id:
            return sim.user
        User = get_user_model()
        return await User.objects.aget(pk=sender_id)

    async def apersist(self, *, response, parsed) -> dict[str, Any]:
        ctx = response.request.context or {}
        sim = await self._aresolve_sim(ctx["simulation_id"])
        sender = await self._aget_sender(ctx.get("sender_id"), sim=sim)

        normalized = parsed.model_dump() if hasattr(parsed, "model_dump") else parsed

        async with transaction.atomic():
            ai_resp = await AIResponse.objects.acreate(
                simulation=sim,
                provider_id=response.provider_response_id,
                raw=response.raw,
                normalized=normalized,
            )

            run_ctx = {"simulation": sim, "sender": sender, "ai_response": ai_resp}

            # Allow dynamic defaults (e.g., inject FK/flags at runtime)
            dyn_defaults = self.make_section_defaults(sim=sim, sender=sender, ai_resp=ai_resp)
            if dyn_defaults:
                # DjangoBaseCodec will read these when calling persist_sections
                self.section_defaults = dyn_defaults  # type: ignore[attr-defined]

            # Fan-out persistence per schema_model_map / translations
            await self.persist_sections(parsed, context=run_ctx)

            if self.create_assistant_message:
                msg_text = self.message_text_provider(parsed)
                if msg_text:
                    await Message.objects.acreate(
                        simulation=sim,
                        sender=sender or sim.user,
                        content=msg_text,
                        role=RoleChoices.ASSISTANT,
                        is_from_ai=True,
                        response=ai_resp,
                    )

        return {"ai_response_id": ai_resp.pk, "simulation_id": sim.pk}