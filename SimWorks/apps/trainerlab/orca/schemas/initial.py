# trainerlab/orca/schemas/initial.py

from datetime import UTC
import logging
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import AliasChoices, Field

from apps.trainerlab.models import (
    ETCO2 as ORMETCO2,
    SPO2 as ORMSPO2,
    BloodGlucoseLevel as ORMBloodGlucoseLevel,
    BloodPressure as ORMBloodPressure,
    HeartRate as ORMHeartRate,
    Illness as ORMIllness,
    Injury as ORMInjury,
)
from orchestrai.types import StrictBaseModel

from .types import ETCO2, SPO2, BloodGlucoseLevel, BloodPressure, HeartRate, Illness, Injury

logger = logging.getLogger(__name__)

__all__ = ["InitialScenarioSchema"]


if TYPE_CHECKING:
    from orchestrai_django.persistence import PersistContext


def _event_timestamp_iso(obj: Any) -> str | None:
    timestamp = getattr(obj, "timestamp", None)
    if timestamp is None:
        return None
    return timestamp.astimezone(UTC).isoformat()


def _condition_event_payload(obj: Any, *, context: "PersistContext") -> dict[str, Any]:
    payload = {
        "simulation_id": getattr(obj, "simulation_id", context.simulation_id),
        "domain_event_id": getattr(obj, "id", None),
        "domain_event_type": type(obj).__name__,
        "source": getattr(obj, "source", None),
        "supersedes_event_id": getattr(obj, "supersedes_event_id", None),
        "timestamp": _event_timestamp_iso(obj),
        "origin": "initial_scenario",
        "call_id": context.call_id,
        "correlation_id": context.correlation_id,
    }

    if isinstance(obj, ORMInjury):
        payload.update(
            {
                "condition_kind": "injury",
                "injury_category": obj.injury_category,
                "injury_location": obj.injury_location,
                "injury_kind": obj.injury_kind,
                "injury_description": obj.injury_description,
                "is_treated": obj.is_treated,
                "is_resolved": obj.is_resolved,
            }
        )
    elif isinstance(obj, ORMIllness):
        payload.update(
            {
                "condition_kind": "illness",
                "name": obj.name,
                "description": obj.description,
                "severity": obj.severity,
                "is_resolved": obj.is_resolved,
            }
        )

    return payload


def _vital_event_payload(obj: Any, *, context: "PersistContext") -> dict[str, Any]:
    if isinstance(obj, ORMHeartRate):
        vital_type = "heart_rate"
    elif isinstance(obj, ORMSPO2):
        vital_type = "spo2"
    elif isinstance(obj, ORMETCO2):
        vital_type = "etco2"
    elif isinstance(obj, ORMBloodGlucoseLevel):
        vital_type = "blood_glucose"
    elif isinstance(obj, ORMBloodPressure):
        vital_type = "blood_pressure"
    else:
        vital_type = type(obj).__name__

    payload = {
        "simulation_id": getattr(obj, "simulation_id", context.simulation_id),
        "domain_event_id": getattr(obj, "id", None),
        "domain_event_type": type(obj).__name__,
        "source": getattr(obj, "source", None),
        "supersedes_event_id": getattr(obj, "supersedes_event_id", None),
        "timestamp": _event_timestamp_iso(obj),
        "origin": "initial_scenario",
        "call_id": context.call_id,
        "correlation_id": context.correlation_id,
        "vital_type": vital_type,
        "min_value": getattr(obj, "min_value", None),
        "max_value": getattr(obj, "max_value", None),
        "lock_value": getattr(obj, "lock_value", None),
    }
    if isinstance(obj, ORMBloodPressure):
        payload["min_value_diastolic"] = obj.min_value_diastolic
        payload["max_value_diastolic"] = obj.max_value_diastolic

    return payload


class MeasurementSchemaBlock(StrictBaseModel):
    heart_rate: HeartRate
    spo2: SPO2
    blood_glucose_level: BloodGlucoseLevel
    blood_pressure: BloodPressure
    etco2: ETCO2 = Field(
        ...,
        validation_alias=AliasChoices("etco2", "etc02"),
        serialization_alias="etco2",
    )

    __persist__: ClassVar[dict[str, None]] = {
        "heart_rate": None,
        "spo2": None,
        "blood_glucose_level": None,
        "blood_pressure": None,
        "etco2": None,
    }


class InitialScenarioSchema(StrictBaseModel):
    """Initial response schema for the ORCA service."""

    conditions: list[Injury | Illness] = Field(
        ...,
        min_length=1,
        description="List of injuries or illnesses",
    )
    measurements: MeasurementSchemaBlock = Field(..., description="Measurement schema block")

    __persist__: ClassVar[dict[str, None]] = {
        "conditions": None,
        "measurements": None,
    }
    __persist_primary__ = "conditions"

    async def post_persist(self, results: dict[str, Any], context: "PersistContext") -> None:
        from apps.common.outbox.helpers import broadcast_domain_objects

        conditions = results.get("conditions", [])
        measurements = results.get("measurements", {})

        vital_objects: list[Any] = []
        if isinstance(measurements, dict):
            for key in (
                "heart_rate",
                "spo2",
                "blood_glucose_level",
                "blood_pressure",
                "etco2",
            ):
                obj = measurements.get(key)
                if obj is not None:
                    vital_objects.append(obj)

        if conditions:
            await broadcast_domain_objects(
                event_type="trainerlab.condition.created",
                objects=conditions,
                context=context,
                payload_builder=lambda obj: _condition_event_payload(obj, context=context),
            )

        if vital_objects:
            await broadcast_domain_objects(
                event_type="trainerlab.vital.created",
                objects=vital_objects,
                context=context,
                payload_builder=lambda obj: _vital_event_payload(obj, context=context),
            )
