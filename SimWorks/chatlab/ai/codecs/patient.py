# chatlab/ai/codecs/patient.py
from __future__ import annotations

from typing import Any, Iterable, Optional, TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db import transaction

from chatlab.ai.mixins import ChatlabMixin
from chatlab.models import Message, RoleChoices
from simcore.ai.mixins import StandardizedPatientMixin
from simcore.models import (
    Simulation,
    AIResponse,
    SimulationMetadata,
    PatientHistory,
    PatientDemographics,
    LabResult,
    RadResult,
)
from simcore_ai_django.api import service_span_sync
from simcore_ai_django.api.decorators import codec
from simcore_ai_django.api.types import DjangoBaseLLMCodec

if TYPE_CHECKING:
    from ..schemas import PatientInitialOutputSchema, PatientReplyOutputSchema, PatientResultsOutputSchema

__all__ = [
    "PatientInitialResponseCodec",
    "PatientReplyCodec",
    "PatientResultsCodec"
]

# ------------------------------
# Helpers
# ------------------------------

def _resolve_simulation(sim_or_id: Any) -> Simulation:
    return Simulation.resolve(sim_or_id)


def _first_message_text(messages: Iterable[dict] | None) -> str:
    if not messages:
        return ""
    try:
        first = next(iter(messages))
    except StopIteration:
        return ""
    if first is None:
        return ""
    # Support both dict-like and object-like items
    if isinstance(first, dict):
        return (first or {}).get("content", "") or ""
    return getattr(first, "content", "") or ""


def _persist_ai_response(*, sim: Simulation, provider_id: Optional[str], raw: Any, normalized: dict) -> AIResponse:
    return AIResponse.objects.create(
        simulation=sim,
        provider_id=provider_id or None,
        raw=raw,
        normalized=normalized,
        # token counts may be enriched later by client/provider adapters
    )


def _persist_message(*, sim: Simulation, sender_id: Optional[int], content: str,
                     ai_resp: Optional[AIResponse]) -> Message:
    User = get_user_model()
    if sender_id is not None:
        sender = User.objects.get(pk=sender_id)
    else:
        # Fallback: attribute to simulation user
        sender = sim.user
    msg = Message.objects.create(
        simulation=sim,
        sender=sender,
        content=content,
        role=RoleChoices.ASSISTANT,
        is_from_ai=True,
        response=ai_resp,
    )
    return msg


def _persist_generic_metadata(sim: Simulation, items: Iterable[dict]) -> None:
    for item in items or []:
        kind = (item or {}).get("kind")
        key = (item or {}).get("key")
        value = (item or {}).get("value")
        if not key:
            continue
        if kind == "patient_history":
            PatientHistory.objects.create(
                simulation=sim,
                key=key,
                value=value or "",
                is_resolved=bool((item or {}).get("is_resolved") or False),
                duration=(item or {}).get("duration") or "",
            )
        elif kind == "patient_demographics":
            PatientDemographics.objects.create(
                simulation=sim,
                key=key,
                value=value or "",
            )
        else:
            # Fallback to base metadata if we don't have a concrete model
            SimulationMetadata.objects.create(
                simulation=sim,
                key=key,
                value=value or "",
            )


def _persist_result_metadata(sim: Simulation, items: Iterable[dict]) -> None:
    for item in items or []:
        kind = (item or {}).get("kind")
        key = (item or {}).get("key")
        if not key:
            continue
        if kind == "lab_result":
            LabResult.objects.create(
                simulation=sim,
                key=key,
                value=(item or {}).get("result_value") or (item or {}).get("value") or "",
                panel_name=(item or {}).get("panel_name") or None,
                result_unit=(item or {}).get("result_unit") or None,
                reference_range_low=(item or {}).get("reference_range_low") or None,
                reference_range_high=(item or {}).get("reference_range_high") or None,
                result_flag=(item or {}).get("result_flag") or "",
                result_comment=(item or {}).get("result_comment") or None,
            )
        elif kind == "rad_result":
            RadResult.objects.create(
                simulation=sim,
                key=key,
                value=(item or {}).get("value") or "",
                result_flag=(item or {}).get("flag") or "",
            )
        else:
            # Unknown result kind → store generically
            SimulationMetadata.objects.create(
                simulation=sim,
                key=key,
                value=(item or {}).get("value") or "",
            )


# ------------------------------
# Codecs
# ------------------------------


@codec
class PatientInitialResponseCodec(ChatlabMixin, StandardizedPatientMixin, DjangoBaseLLMCodec):
    """
    Codec for the **initial patient response** in ChatLab.

    - Validates against `PatientInitialOutputSchema`
    - Persists `AIResponse`, an assistant `Message` (first message content),
      and any `metadata` (patient history/demographics/etc.)

    Context expectations (from service request):
    - `simulation` or `simulation_id`: Simulation instance or pk
    - Optional `sender_id`: user pk to attribute the assistant message (else simulation.user)
    """

    @transaction.atomic
    def persist(self, *, response, parsed: PatientInitialOutputSchema) -> dict:
        with service_span_sync(
                "codec.persist",
                attributes={
                    "ai.identity.codec": f"{getattr(self, 'origin', '?')}.{getattr(self, 'bucket', '?')}.{getattr(self, 'name', '?')}",
                    "codec_class": self.__class__.__name__,
                },
        ):
            sim = _resolve_simulation(
                response.request.context.get("simulation")
                or response.request.context.get("simulation_id")
            )
            msg_text = _first_message_text(parsed.messages)

            normalized = parsed.model_dump()
            ai_resp = _persist_ai_response(
                sim=sim,
                provider_id=response.provider_response_id,
                raw=response.raw,
                normalized=normalized,
            )
            _persist_message(
                sim=sim,
                sender_id=response.request.context.get("sender_id"),
                content=msg_text,
                ai_resp=ai_resp,
            )
            _persist_generic_metadata(sim, parsed.metadata)
            return {"ai_response_id": ai_resp.pk, "simulation_id": sim.pk}


@codec
class PatientReplyCodec(ChatlabMixin, StandardizedPatientMixin, DjangoBaseLLMCodec):
    """Codec for subsequent **patient replies** in ChatLab.

    - Validates against `PatientReplyOutputSchema`
    - Persists `AIResponse` and an assistant `Message` (first message content)
    """

    @transaction.atomic
    def persist(self, *, response, parsed: PatientReplyOutputSchema) -> dict:
        with service_span_sync(
                "codec.persist",
                attributes={
                    "ai.identity.codec": f"{getattr(self, 'origin', '?')}.{getattr(self, 'bucket', '?')}.{getattr(self, 'name', '?')}",
                    "codec_class": self.__class__.__name__,
                },
        ):
            sim = _resolve_simulation(
                response.request.context.get("simulation")
                or response.request.context.get("simulation_id")
            )
            msg_text = _first_message_text(parsed.messages)

            normalized = parsed.model_dump()
            ai_resp = _persist_ai_response(
                sim=sim,
                provider_id=response.provider_response_id,
                raw=response.raw,
                normalized=normalized,
            )
            _persist_message(
                sim=sim,
                sender_id=response.request.context.get("sender_id"),
                content=msg_text,
                ai_resp=ai_resp,
            )
            return {"ai_response_id": ai_resp.pk, "simulation_id": sim.pk}


@codec
class PatientResultsCodec(ChatlabMixin, StandardizedPatientMixin, DjangoBaseLLMCodec):
    """Codec for **diagnostic results** (labs/rads) returned by the model.

    - Validates against `PatientResultsOutputSchema`
    - Persists `AIResponse` and result metadata rows (LabResult/RadResult)
    """

    @transaction.atomic
    def persist(self, *, response, parsed: PatientResultsOutputSchema) -> dict:
        with service_span_sync(
                "codec.persist",
                attributes={
                    "ai.identity.codec": f"{getattr(self, 'origin', '?')}.{getattr(self, 'bucket', '?')}.{getattr(self, 'name', '?')}",
                    "codec_class": self.__class__.__name__,
                },
        ):
            sim = _resolve_simulation(
                response.request.context.get("simulation")
                or response.request.context.get("simulation_id")
            )

            normalized = parsed.model_dump()
            ai_resp = _persist_ai_response(
                sim=sim,
                provider_id=response.provider_response_id,
                raw=response.raw,
                normalized=normalized,
            )
            _persist_result_metadata(sim, parsed.metadata)
            return {"ai_response_id": ai_resp.pk, "simulation_id": sim.pk}
