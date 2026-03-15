# trainerlab/orca/schemas/initial.py

import logging
from typing import TYPE_CHECKING, Annotated, Any, ClassVar

from asgiref.sync import sync_to_async
from pydantic import AliasChoices, Field

from apps.trainerlab.event_payloads import serialize_domain_event
from apps.trainerlab.schemas import ScenarioBrief
from orchestrai.types import StrictBaseModel

from .types import (
    ETCO2,
    SPO2,
    BloodGlucoseLevel,
    BloodPressure,
    HeartRate,
    Illness,
    Injury,
    RespiratoryRate,
)

logger = logging.getLogger(__name__)

__all__ = ["InitialScenarioSchema"]


if TYPE_CHECKING:
    from orchestrai_django.persistence import PersistContext


def _initial_extra(context: "PersistContext") -> dict[str, Any]:
    return {
        "origin": "initial_scenario",
        "call_id": str(context.call_id),
        "correlation_id": context.correlation_id,
    }


class MeasurementSchemaBlock(StrictBaseModel):
    heart_rate: HeartRate
    respiratory_rate: RespiratoryRate
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
        "respiratory_rate": None,
        "spo2": None,
        "blood_glucose_level": None,
        "blood_pressure": None,
        "etco2": None,
    }


ConditionSchema = Annotated[Injury | Illness, Field(discriminator="kind")]


class InitialScenarioSchema(StrictBaseModel):
    """Initial response schema for the ORCA service."""

    scenario_brief: ScenarioBrief = Field(
        ...,
        description=(
            "Instructor-facing scenario brief that includes the read-aloud opening context and "
            "high-level environmental details."
        ),
    )
    conditions: list[ConditionSchema] = Field(
        ...,
        min_length=1,
        description="List of injuries or illnesses",
    )
    measurements: MeasurementSchemaBlock = Field(..., description="Measurement schema block")

    __persist__: ClassVar[dict[str, None]] = {
        "scenario_brief": None,
        "conditions": None,
        "measurements": None,
    }
    __persist_primary__ = "conditions"

    async def post_persist(self, results: dict[str, Any], context: "PersistContext") -> None:
        from apps.common.outbox.helpers import broadcast_domain_objects
        from apps.trainerlab.services import refresh_projection_from_domain_state

        scenario_brief_obj = results.get("scenario_brief")
        conditions = results.get("conditions", [])
        measurements = results.get("measurements", {})

        vital_objects: list[Any] = []
        if isinstance(measurements, dict):
            for key in (
                "heart_rate",
                "respiratory_rate",
                "spo2",
                "blood_glucose_level",
                "blood_pressure",
                "etco2",
            ):
                obj = measurements.get(key)
                if obj is not None:
                    vital_objects.append(obj)

        extra = _initial_extra(context)

        if scenario_brief_obj is not None:
            await broadcast_domain_objects(
                event_type="trainerlab.scenario_brief.created",
                objects=[scenario_brief_obj],
                context=context,
                payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
            )

        if conditions:
            await broadcast_domain_objects(
                event_type="trainerlab.condition.created",
                objects=conditions,
                context=context,
                payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
            )

        if vital_objects:
            await broadcast_domain_objects(
                event_type="trainerlab.vital.created",
                objects=vital_objects,
                context=context,
                payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
            )

        await sync_to_async(refresh_projection_from_domain_state, thread_sensitive=True)(
            simulation_id=context.simulation_id,
            correlation_id=context.correlation_id,
        )
