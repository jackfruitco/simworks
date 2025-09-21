# simcore/ai/utils/persist.py
import logging
from typing import TYPE_CHECKING
from typing import Awaitable, Callable, Type, Dict, Any


from core.utils import get_or_create_system_user
from asgiref.sync import sync_to_async
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
    NormalizedAIMetadata,
)

if TYPE_CHECKING:
    from simcore.models import Simulation, SimulationMetadata


logger = logging.getLogger(__name__)


# ---------- Internal async creators / helpers ---------------------------------------
async def _create_metadata(model_cls, sim, *, key: str, value: str = "", **extra):
    return await model_cls.objects.acreate(simulation=sim, key=key, value=value or "", **extra)

async def _persist_lab_result(sim, meta):
    from simcore.models import LabResult
    return await _create_metadata(
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
    return await _create_metadata(RadResult, sim, key=meta.key, value=meta.value, result_flag=meta.flag)

async def _persist_patient_history(sim, meta):
    from simcore.models import PatientHistory
    return await _create_metadata(
        PatientHistory,
        sim,
        key=meta.key,
        value=meta.value or str(None),
        is_resolved=meta.is_resolved,
        duration=meta.duration,
    )

async def _persist_feedback(sim, meta):
    from simcore.models import SimulationFeedback
    return await _create_metadata(SimulationFeedback, sim, key=meta.key, value=meta.value)

async def _persist_demographics(sim, meta):
    from simcore.models import PatientDemographics
    return await _create_metadata(PatientDemographics, sim, key=meta.key, value=meta.value)

async def _persist_sim_kv(sim, meta):
    from simcore.models import SimulationMetadata
    return await _create_metadata(SimulationMetadata, sim, key=meta.key, value=(meta.value or ""))

async def _persist_scenario(sim, meta):
    from simcore.models import SimulationMetadata
    # Update Simulation known fields
    field_map = {"diagnosis": "diagnosis", "chief_complaint": "chief_complaint"}
    if meta.key in field_map:
        setattr(sim, field_map[meta.key], meta.value or "")
        await sync_to_async(sim.save)(update_fields=[field_map[meta.key]])
    # Also persist a KV row for auditability
    return await _create_metadata(SimulationMetadata, sim, key=meta.key, value=(meta.value or ""))

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


async def _map_user(role: str, sim: "Simulation") -> tuple[str, "User"]:
    # Map normalized roles to ChatLab DB choices
    r = (role or "").lower()
    if r in {"assistant", "developer", "system", "patient"}:
        return "A", await _resolve_system_user()  # RoleChoices.ASSISTANT
    return "U", sim.user  # RoleChoices.USER


async def persist_metadata(s: "Simulation", m: NormalizedAIMetadata) -> "SimulationMetadata":
    # Resolve the first matching handler by isinstance to allow subclassing
    for cls, handler in _META_PERSIST_HANDLERS.items():
        if isinstance(m, cls):
            instance = await handler(s, m)
            # attach pk back onto the normalized DTO for upstream use
            try:
                m.instance_id = getattr(instance, "pk", None)
            except Exception:
                pass
            return instance
    # As a last resort, persist as generic KV
    from simcore.models import SimulationMetadata
    instance = await SimulationMetadata.objects.acreate(
        simulation=s, key=getattr(m, "key", "meta"), value=getattr(m, "value", "") or ""
    )

    m.db_pk = getattr(instance, "pk", None)

    logger.debug(f"... persisted metafield ("
                 f"`{instance.__class__.__name__}` id {instance.pk}; "
                 f"`Simulation` id {s.pk})"
                 )

    return m


async def persist_message(s: "Simulation", m: NormalizedAIMessage) -> NormalizedAIMessage:
    # Lazy import of Message to avoid circulars if any
    # TODO move Message to simcore.models
    from chatlab.models import Message
    _role, _sender = await _map_user(m.role, s)

    data = {
        "simulation": s,
        "role": _role,
        "sender": _sender,
        "content": m.content,
        # "message_type": m.message_type,       # TODO
        # "media": m.media,                     # TODO
        "is_from_ai": True,  # TODO
        # "openai_id"                           # TODO
        # "display_name"                        # TODO
    }

    instance = await Message.objects.acreate(**data)
    m.db_pk = getattr(instance, "pk", None)

    logger.debug(f"... persisted message ("
                 f"`{instance.__class__.__name__}` id {instance.pk}; "
                 f"`Simulation` id {s.pk})"
                 )

    return m
