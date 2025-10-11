# simcore/ai/utils/persist.py
import base64
import logging
import mimetypes
import uuid
from typing import Awaitable, Callable, Type, Dict, Any
from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async
from django.core.files.base import ContentFile

from core.utils import get_or_create_system_user
from simcore.ai.schemas.types import (
    MessageItem,
    MetafieldItem,
    LLMResponse,
    AttachmentItem,
    # Metafield DTO classes
    GenericMetafield,
    LabResultMetafield,
    RadResultMetafield,
    PatientHistoryMetafield,
    PatientDemographicsMetafield,
    SimulationMetafield,
    ScenarioMetafield,
    CorrectDiagnosisFeedback,
    CorrectTreatmentPlanFeedback,
    PatientExperienceFeedback,
    OverallFeedbackMetafield,
)

if TYPE_CHECKING:
    from simcore.models import Simulation, SimulationMetadata

logger = logging.getLogger(__name__)


def success_msg(
        instance_cls: str,
        instance_pk: int,
        simulation_pk: int,
        fallback: bool = False,
) -> str:
    """Log a successful persistence operation."""
    msg = f"... persisted {instance_cls} metafield "
    msg += "using fallback to generic KV " if fallback else ""
    msg += f"(pk {instance_pk}; `Simulation` pk {simulation_pk})"
    return msg or ""


# ---------- Internal async creators / helpers ---------------------------------------
async def _create_metadata(model_cls, sim, *, key: str, value: str = "", **extra):
    return await model_cls.objects.acreate(simulation=sim, key=key, value=value or "", **extra)


async def _upsert(model_cls, sim, *, key: str, value: str = "", **extra):
    instance, _ = await model_cls.objects.aupdate_or_create(
        simulation=sim,
        key=key,
        defaults={"value": value or "", **extra},
    )
    return instance


async def _persist_lab_result(sim, meta):
    from simcore.models import LabResult

    logger.debug(
        f"Persisting LabResult: {getattr(meta, "value", None)}",
    )

    return await _upsert(
        LabResult,
        sim,
        key=meta.key,
        value=meta.result_value,
        result_unit=meta.result_unit,
        reference_range_low=meta.reference_range_low,
        reference_range_high=meta.reference_range_high,
        result_flag=meta.result_flag,
        panel_name=meta.panel_name,
    )


async def _persist_rad_result(sim, meta):
    from simcore.models import RadResult
    return await _upsert(RadResult, sim, key=meta.key, value=meta.value, result_flag=meta.flag)


async def _persist_patient_history(sim, meta):
    from simcore.models import PatientHistory
    return await _upsert(
        PatientHistory,
        sim,
        key=meta.key,
        value=meta.value or str(None),
        is_resolved=meta.is_resolved,
        duration=meta.duration,
    )


async def _persist_feedback(sim, meta):
    from simcore.models import SimulationFeedback
    return await _upsert(SimulationFeedback, sim, key=meta.key, value=meta.value)


async def _persist_demographics(sim, meta):
    from simcore.models import PatientDemographics
    return await _upsert(PatientDemographics, sim, key=meta.key, value=meta.value)


async def _persist_sim_kv(sim, meta):
    from simcore.models import SimulationMetadata
    return await _upsert(SimulationMetadata, sim, key=meta.key, value=(meta.value or ""))


async def _persist_scenario(sim, meta):
    from simcore.models import SimulationMetadata
    # Update Simulation known fields
    field_map = {"diagnosis": "diagnosis", "chief_complaint": "chief_complaint"}
    if meta.key in field_map:
        setattr(sim, field_map[meta.key], meta.value or "")
        await sync_to_async(sim.save)(update_fields=[field_map[meta.key]])
    # Also persist a KV row for auditability
    return await _upsert(SimulationMetadata, sim, key=meta.key, value=(meta.value or ""))


# Map normalized meta model -> persistence coroutine
_META_PERSIST_HANDLERS: Dict[Type[Any], Callable[[Any, Any], Awaitable[Any]]] = {}


def _register(meta_cls: Type[Any], handler: Callable[[Any, Any], Awaitable[Any]]) -> None:
    _META_PERSIST_HANDLERS[meta_cls] = handler


# Registration (add new meta types here to extend persistence without touching core logic)
_register(LabResultMetafield, _persist_lab_result)
_register(RadResultMetafield, _persist_rad_result)
_register(PatientHistoryMetafield, _persist_patient_history)
_register(PatientDemographicsMetafield, _persist_demographics)
_register(SimulationMetafield, _persist_sim_kv)
_register(ScenarioMetafield, _persist_scenario)
_register(GenericMetafield, _persist_sim_kv)  # generic fallback
_register(CorrectDiagnosisFeedback, _persist_feedback)
_register(CorrectTreatmentPlanFeedback, _persist_feedback)
_register(PatientExperienceFeedback, _persist_feedback)
_register(OverallFeedbackMetafield, _persist_feedback)


async def _resolve_system_user() -> "User":
    return await sync_to_async(get_or_create_system_user)()


async def _map_user(role: str, sim: "Simulation") -> tuple[str, "User", str | None]:
    # Map normalized roles to ChatLab DB choices
    r = (role or "").lower()
    if r in {"assistant", "developer", "system", "patient", "instructor"}:
        # return example: ("A", <User: System>, "John D.")
        display_name = "Stitch" if r == "instructor" else sim.sim_patient_display_name
        return "A", await _resolve_system_user(), display_name
    # return example: ("U", <User: John D.>)
    return "U", sim.user, None


async def persist_metadata(
        simulation: "Simulation", metadata: MetafieldItem
) -> MetafieldItem:
    """Persist a normalized AI metadata object to the database."""
    # Resolve the first matching handler by isinstance to allow subclassing
    for cls, handler in _META_PERSIST_HANDLERS.items():
        if isinstance(metadata, cls):
            # create the instance, then
            # attach the PK back onto the normalized DTO
            instance = await handler(simulation, metadata)
            metadata.db_pk = getattr(instance, "pk", None)

            logger.debug(success_msg(
                instance.__class__.__name__, instance.pk, simulation.pk
            ))
            return metadata

    # create the instance, then attach the PK back onto the normalized DTO
    # fallback; persist as generic KV
    from simcore.models import SimulationMetadata
    instance, _ = await SimulationMetadata.objects.aupdate_or_create(
        simulation=simulation,
        key=getattr(metadata, "key", "meta"),
        defaults={
            "value": getattr(metadata, "value", "") or ""
        },
    )
    metadata.db_pk = getattr(instance, "pk", None)

    logger.debug(success_msg(
        instance.__class__.__name__,
        instance.pk,
        simulation.pk,
        fallback=True
    ))

    return metadata


async def persist_message(
        simulation: "Simulation",
        message: MessageItem,
        **kwargs,
) -> MessageItem:
    """Persist a normalized AI message to the database."""
    # Lazy import of Message to avoid circulars if any
    # TODO move Message to simcore.models
    from chatlab.models import Message
    _role, _sender, _display = await _map_user(message.role, simulation)

    data = {
        "simulation": simulation,
        "role": _role,
        "sender": _sender,
        "content": message.content,
        # "message_type": m.message_type,       # TODO
        # "media": m.media,                     # TODO
        "is_from_ai": True,  # TODO
        "provider_response_id": kwargs.pop("provider_response_id", None),
        "display_name": _display,
    }

    # create the instance, then attach the PK back onto the normalized DTO
    instance = await Message.objects.acreate(**data)
    message.db_pk = getattr(instance, "pk", None)

    logger.debug(success_msg(instance.__class__.__name__, instance.pk, simulation.pk))

    return message


async def persist_response(
        simulation: Any, response: LLMResponse
) -> LLMResponse:
    """Persist a normalized AI response to the database."""
    from simcore.models import Simulation, AIResponse

    simulation = await Simulation.aresolve(simulation)

    # Pop raw Provider Response from meta, then ensure it is a dict
    # Provider normalization methods should have already dumped to JSON-safe dict
    provider_response = response.provider_meta.pop("provider_response", None)
    if not isinstance(provider_response, dict):
        logger.warning(
            f"Provider response is not a dict (got "
            f"{type(provider_response).__name__}). "
            f"Skipping raw persistence."
        )
        provider_response = None

    data = {
        "simulation": simulation,
        "provider": response.provider_meta.get("provider"),
        "provider_id": response.provider_meta.get("provider_response_id"),
        "raw": provider_response,
        "normalized": response.model_dump(),
        "input_tokens": response.usage.get("input_tokens") or 0,
        "output_tokens": response.usage.get("output_tokens") or 0,
        "reasoning_tokens": response.usage.get("reasoning_tokens") or 0,
    }

    # create the instance, then attach the PK back onto the normalized DTO
    instance = await AIResponse.objects.acreate(**data)
    response.db_pk = getattr(instance, "pk", None)

    logger.debug(success_msg(instance.__class__.__name__, instance.pk, simulation.pk))

    return response


async def persist_attachment(
        attachment: AttachmentItem, simulation: Any
) -> AttachmentItem:
    """Persist a normalized AI attachment to the database."""
    from simcore.models import Simulation, SimulationImage

    # Resolve simulation
    simulation = await Simulation.aresolve(simulation)

    if not getattr(attachment, "b64", None):
        raise ValueError("Attachment has no base64 content (b64).")

    # Guess MIME type from the declared format (e.g., 'webp', 'png', 'jpeg')
    ext = (attachment.format or "").lstrip(".")
    mime_type_ = mimetypes.guess_type(f"temp.{ext}")[0] or "application/octet-stream"

    # Decode and build an in-memory file
    try:
        image_bytes = base64.b64decode(attachment.b64)
        provider_id = (
                attachment.provider_meta.get("provider_response_id")
                or attachment.provider_meta.get("provider_id")
        )
        file_id = provider_id or str(uuid.uuid4())
        image_file = ContentFile(image_bytes, name=f"temp_{file_id}.{ext}")
    except Exception as e:
        # Keep the message specific to decoding/file prep
        raise Exception(f"Failed to decode/prepare image file: {e}") from e

    attachment.file = image_file

    # Create DB instance
    data = {
        "simulation": simulation,
        "original": image_file,
        "mime_type": mime_type_,
    }
    # Persist provider id if your model supports it
    if hasattr(SimulationImage, "provider_id") and provider_id:
        data["provider_id"] = provider_id

    instance = await SimulationImage.objects.acreate(**data)

    # Reflect DB info back to DTO
    attachment.db_pk = getattr(instance, "pk", None)
    attachment.slug = getattr(instance, "slug", None)

    if hasattr(attachment, "db_model"):
        attachment.db_model = instance.__class__.__name__

    try:
        logger.debug(success_msg(instance.__class__.__name__, instance.pk, simulation.pk))
    except Exception:
        logger.debug("log_success failed for SimulationImage persist.", exc_info=True)

    return attachment


async def persist_all(response: LLMResponse, simulation: Any):
    """
    Persist full response, including messages and metadata, for the given Simulation.

    Uses each item's own persistence function to keep concerns separated.

    TODO: create Response instance first to use as fk to message and metadata, then response with db_pks

    :param response: The normalized AI response object
    :type response: LLMResponse

    :param simulation: The Simulation instance or int (pk)
    :type simulation: Simulation or int

    :return: The response DTO, updated with db_pks
    :rtype: LLMResponse

    :raises Exception: If any of the persist calls fail
    """
    prov_id = response.provider_meta.get("provider_response_id") or response.provider_meta.get("provider_id")

    # Persist messages
    for m in response.messages:
        try:
            await persist_message(simulation, m, provider_response_id=prov_id)
        except Exception:
            logger.exception("failed to persist message! %r", m)

        if m.attachments:
            for a in m.attachments:
                try:
                    await persist_attachment(a, simulation)
                except Exception:
                    logger.exception("failed to persist attachment! %r", a)

    # Persist metadata
    for metafield in response.metadata:
        try:
            await persist_metadata(simulation, metafield)
        except Exception:
            logger.exception("failed to persist metafield! %r", metafield)

    # Persist the response itself
    try:
        await persist_response(simulation, response)
    except Exception:
        logger.exception("failed to persist response! %r", response)

    return response
