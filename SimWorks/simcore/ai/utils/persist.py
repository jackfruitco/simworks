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
from simcore.ai.schemas.normalized_types import (
    NormalizedAIMessage,
    GenericMeta,
    LabResultMeta,
    RadResultMeta,
    PatientHistoryMeta,
    SimulationFeedbackMeta,
    PatientDemographicsMeta,
    SimulationMetaKV,
    ScenarioMeta,
    NormalizedAIMetadata, NormalizedAIResponse, NormalizedAttachment,
)

if TYPE_CHECKING:
    from simcore.models import Simulation, SimulationMetadata

logger = logging.getLogger(__name__)


def log_success(
        instance_cls: str,
        instance_pk: int,
        simulation_pk: int,
        fallback: bool = False,
) -> None:
    """Log a successful persistence operation."""
    msg = f"... persisted {instance_cls} "
    msg += "using fallback to generic KV " if fallback else ""
    msg += f"(pk {instance_pk}; `Simulation` pk {simulation_pk})"
    logger.debug(msg)
    return


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
    return await _upsert(
        LabResult,
        sim,
        key=meta.key,
        value=meta.value,
        result_unit=meta.unit,
        reference_range_low=meta.ref_low,
        reference_range_high=meta.ref_high,
        result_flag=meta.flag,
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
_register(LabResultMeta, _persist_lab_result)
_register(RadResultMeta, _persist_rad_result)
_register(PatientHistoryMeta, _persist_patient_history)
_register(SimulationFeedbackMeta, _persist_feedback)
_register(PatientDemographicsMeta, _persist_demographics)
_register(SimulationMetaKV, _persist_sim_kv)
_register(ScenarioMeta, _persist_scenario)
_register(GenericMeta, _persist_sim_kv)  # generic fallback


async def _resolve_system_user() -> "User":
    return await sync_to_async(get_or_create_system_user)()


async def _map_user(role: str, sim: "Simulation") -> tuple[str, "User", str | None]:
    # Map normalized roles to ChatLab DB choices
    r = (role or "").lower()
    if r in {"assistant", "developer", "system", "patient"}:
        # return example: ("A", <User: System>, "John D.")
        return "A", await _resolve_system_user(), sim.sim_patient_display_name
    # return example: ("U", <User: John D.>)
    return "U", sim.user, None


async def persist_metadata(
        simulation: "Simulation", metadata: NormalizedAIMetadata
) -> NormalizedAIMetadata:
    """Persist a normalized AI metadata object to the database."""
    # Resolve the first matching handler by isinstance to allow subclassing
    for cls, handler in _META_PERSIST_HANDLERS.items():
        if isinstance(metadata, cls):
            # create the instance, then
            # attach the PK back onto the normalized DTO
            instance = await handler(simulation, metadata)
            metadata.db_pk = getattr(instance, "pk", None)

            log_success(
                instance.__class__.__name__, instance.pk, simulation.pk
            )
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

    log_success(
        instance.__class__.__name__,
        instance.pk,
        simulation.pk,
        fallback=True
    )

    return metadata


async def persist_message(
        simulation: "Simulation",
        message: NormalizedAIMessage,
        **kwargs,
) -> NormalizedAIMessage:
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

    log_success(instance.__class__.__name__, instance.pk, simulation.pk)

    return message


async def persist_response(
        simulation: Any, response: NormalizedAIResponse
) -> NormalizedAIResponse:
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

    log_success(instance.__class__.__name__, instance.pk, simulation.pk)

    return response


async def persist_attachment(
        attachment: NormalizedAttachment, simulation: Any
) -> NormalizedAttachment:
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

    # Attach the file to the DTO (if your DTO has this field)
    attachment.file = image_file

    # Create DB row
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
        log_success(instance.__class__.__name__, instance.pk, simulation.pk)
    except Exception:
        logger.debug("log_success failed for SimulationImage persist.", exc_info=True)

    return attachment


async def persist_all(response: NormalizedAIResponse, simulation: Any):
    """
    Persist full response, including messages and metadata, for the given Simulation.

    Uses each item's own `.persist()` convenience method to keep concerns separated.

    TODO: create Response instance first to use as fk to message and metadata, then response with db_pks

    :param response: The normalized AI response object
    :type response: NormalizedAIResponse

    :param simulation: The Simulation instance or int (pk)
    :type simulation: Simulation or int

    :return: The response DTO, updated with db_pks
    :rtype: NormalizedAIResponse

    :raises Exception: If any of the persist calls fail
    """
    prov_id = response.provider_meta.get("provider_response_id") or response.provider_meta.get("provider_id")

    # Persist messages
    for m in response.messages:
        try:
            await m.persist(simulation, provider_response_id=prov_id)
        except Exception:
            logger.exception("failed to persist message! %r", m)

        if m.attachments:
            for a in m.attachments:
                try:
                    await persist_attachment(a, simulation)
                except Exception:
                    logger.exception("failed to persist attachment! %r", a)

    # Persist metadata
    for mf in response.metadata:
        try:
            await mf.persist(simulation)
        except Exception:
            logger.exception("failed to persist metafield! %r", mf)

    # Persist the response itself
    try:
        await response.persist_response(simulation)
    except Exception:
        logger.exception("failed to persist response! %r", response)

    return response
