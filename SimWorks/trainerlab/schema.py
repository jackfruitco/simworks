

from typing import List, Optional
from datetime import datetime
from enum import Enum

import strawberry
import strawberry_django
from strawberry import ID

from simcore.schema import SimulationType
from .models import (
    TrainerSession,
    ABCEvent,
    Injury,
    Intervention,
    VitalMeasurement,
    HeartRate,
    SPO2,
    ETCO2,
    BloodGlucoseLevel,
    BloodPressure,
)

@strawberry.enum
class MeasurementKind(str, Enum):
    HR = "hr"
    SPO2 = "spo2"
    ETCO2 = "etco2"
    BGL = "bgl"
    BP = "bp"

# ──────────────────────────────────────────────────────────────────────────────
# Base / Simple Types
# ──────────────────────────────────────────────────────────────────────────────

@strawberry_django.type(model=TrainerSession)
class TrainerSessionType:
    id: ID
    simulation: SimulationType


# ──────────────────────────────────────────────────────────────────────────────
# Interfaces
# ──────────────────────────────────────────────────────────────────────────────

# Base event shared by all concrete events
@strawberry_django.interface(model=ABCEvent)
class ABCEventInterface:
    id: ID
    timestamp: datetime

    # We avoid importing the Simulation type to prevent cross-app cycles; expose an ID.
    @strawberry.field
    def simulation_id(self) -> ID:
        return ID(str(self.simulation_id))

    @strawberry.field
    def kind(self) -> str:
        return self._meta.model_name


# VitalMeasurement is abstract; expose common fields via an interface.
@strawberry_django.interface(model=VitalMeasurement)
class VitalMeasurementInterface(ABCEventInterface):
    min_value: int
    max_value: int
    lock_value: bool

    # Computed helpers from model properties
    @strawberry.field
    def unit(self) -> str:
        return str(self.unit)

    @strawberry.field
    def friendly_name(self) -> str:
        return str(self.friendly_name)

    @strawberry.field
    def abbreviated_name(self) -> str:
        return str(self.abbreviated_name)


# ──────────────────────────────────────────────────────────────────────────────
# Concrete Event Types
# ──────────────────────────────────────────────────────────────────────────────

@strawberry_django.type(model=Injury)
class InjuryType(ABCEventInterface,):
    injury_category: str
    injury_location: str
    injury_kind: str
    injury_description: str
    is_treated: bool
    is_resolved: bool

    parent_injury: Optional["InjuryType"]

    # Convenience displays mirroring Django's get_FOO_display()
    @strawberry.field
    def injury_category_display(self) -> str:
        return self.get_injury_category_display()

    @strawberry.field
    def injury_location_display(self) -> str:
        return self.get_injury_location_display()

    @strawberry.field
    def injury_kind_display(self) -> str:
        return self.get_injury_kind_display()

    @strawberry.field
    def is_parent_injury(self) -> bool:
        return self.parent_injury_id is None

    @strawberry.field
    def is_child_injury(self) -> bool:
        return self.parent_injury_id is not None

    @strawberry.field
    def original_injury(self) -> "InjuryType":
        return self.parent_injury or self


@strawberry_django.type(model=Intervention)
class InterventionType(ABCEventInterface):
    pass


@strawberry_django.type(model=HeartRate)
class HeartRateType(VitalMeasurementInterface):
    pass


@strawberry_django.type(model=SPO2)
class SPO2Type(VitalMeasurementInterface):
    pass


@strawberry_django.type(model=ETCO2)
class ETCO2Type(VitalMeasurementInterface):
    pass


@strawberry_django.type(model=BloodGlucoseLevel)
class BloodGlucoseLevelType(VitalMeasurementInterface):
    pass


@strawberry_django.type(model=BloodPressure)
class BloodPressureType(VitalMeasurementInterface):
    min_value_diastolic: int
    max_value_diastolic: int

    # Aliases to match the model's convenience properties
    @strawberry.field
    def min_value_systolic(self) -> int:
        return int(self.min_value)

    @strawberry.field
    def max_value_systolic(self) -> int:
        return int(self.max_value)


# ──────────────────────────────────────────────────────────────────────────────
# Unions
# ──────────────────────────────────────────────────────────────────────────────

EventUnion = strawberry.union(
    "EventUnion",
    (
        InjuryType,
        InterventionType,
        HeartRateType,
        SPO2Type,
        ETCO2Type,
        BloodGlucoseLevelType,
        BloodPressureType,
    ),
)

VitalUnion = strawberry.union(
    "VitalUnion",
    (
        HeartRateType,
        SPO2Type,
        ETCO2Type,
        BloodGlucoseLevelType,
        BloodPressureType,
    ),
)


# ──────────────────────────────────────────────────────────────────────────────
# Query Root
# ──────────────────────────────────────────────────────────────────────────────

@strawberry.type
class TrainerLabQuery:
    # Sessions
    @strawberry_django.field
    def trainer_session(self, info: strawberry.Info, id: ID) -> Optional[TrainerSessionType]:
        try:
            return TrainerSession.objects.get(pk=id)
        except TrainerSession.DoesNotExist:
            return None

    @strawberry_django.field
    def trainer_sessions(self, info: strawberry.Info, limit: Optional[int] = None) -> List[TrainerSessionType]:
        qs = TrainerSession.objects.all().order_by("-id")
        return qs[:limit] if limit else qs

    # Injuries
    @strawberry_django.field
    def injuries(
        self,
        info: strawberry.Info,
        simulation: Optional[ID] = None,
        parent_only: Optional[bool] = None,
        limit: Optional[int] = None,
    ) -> List[InjuryType]:
        qs = Injury.objects.all().order_by("-timestamp")
        if simulation:
            qs = qs.filter(simulation_id=simulation)
        if parent_only is True:
            qs = qs.filter(parent_injury__isnull=True)
        if parent_only is False:
            qs = qs.filter(parent_injury__isnull=False)
        return qs[:limit] if limit else qs

    # Vital signs (all concrete vital models)
    @strawberry_django.field(permission_classes=[])
    def measurements(
            self,
            info: strawberry.Info,
            simulation: Optional[ID] = None,
            limit: Optional[int] = None
    ) -> List[VitalUnion]:
        items: list[ABCEvent] = []
        for model in (HeartRate, SPO2, ETCO2, BloodGlucoseLevel, BloodPressure):
            qs = model.objects.all()
            if simulation:
                qs = qs.filter(simulation_id=simulation)
            items.extend(qs)
        items.sort(key=lambda e: e.timestamp, reverse=True)
        return items[:limit] if limit else items

    # All events as a union (use carefully for timelines)
    @strawberry_django.field(permission_classes=[])
    def events(
        self,
        info: strawberry.Info,
        simulation: Optional[ID] = None,
        kinds: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[EventUnion]:
        """Return a mixed, reverse-chronological list of events.

        kinds can restrict to: "injury", "intervention", "hr", "spo2", "etco2", "bgl", "bp".
        """
        queryset_map = {
            "injury": Injury.objects.all(),
            "intervention": Intervention.objects.all(),
            "hr": HeartRate.objects.all(),
            "spo2": SPO2.objects.all(),
            "etco2": ETCO2.objects.all(),
            "bgl": BloodGlucoseLevel.objects.all(),
            "bp": BloodPressure.objects.all(),
        }

        selected = queryset_map.keys() if not kinds else [k for k in kinds if k in queryset_map]
        items: List[ABCEvent] = []
        for k in selected:
            qs = queryset_map[k]
            if simulation:
                qs = qs.filter(simulation_id=simulation)
            items.extend(list(qs))

        # Sort mixed events by timestamp desc
        items.sort(key=lambda e: e.timestamp, reverse=True)
        return items[:limit] if limit else items


@strawberry.type
class TrainerLabMutation:
    @strawberry_django.mutation(permission_classes=[])
    async def create_session(
            self,
            info: strawberry.Info,
            user: strawberry.ID,
            modifiers: Optional[List[str]] = None,
            force: bool = False
    ) -> TrainerSessionType:
        from .utils import create_new_simulation
        return await create_new_simulation(
            user=user,
            modifiers=modifiers,
            force=force,
            request_session=True,
        )

    @strawberry_django.mutation(permission_classes=[])
    async def create_measurement(
        self,
        info: strawberry.Info,
        simulation_id: ID,
        kind: MeasurementKind,
        min_value: int,
        max_value: Optional[int] = None,
        lock_value: bool = False,
        # Only required when kind == BP
        min_value_diastolic: Optional[int] = None,
        max_value_diastolic: Optional[int] = None,
    ) -> VitalUnion | None:
        """Create a new vital measurement event.

        Notes:
        - Defaults `max_value` to `min_value` if not provided.
        - Validates ranges and BP-specific diastolic values.
        - Returns the created model instance; strawberry-django projects it to the correct concrete GraphQL type implementing `VitalMeasurementInterface`.
        """
        # Default max to min to satisfy min<=max constraint and support lock_value
        if max_value is None:
            max_value = min_value

        # Common validation
        if min_value > max_value:
            raise ValueError("min_value cannot be greater than max_value")

        if kind == MeasurementKind.BP:
            if min_value_diastolic is None or max_value_diastolic is None:
                raise ValueError("BloodPressure requires min_value_diastolic and max_value_diastolic")
            if min_value_diastolic > max_value_diastolic:
                raise ValueError("Diastolic min cannot be greater than diastolic max")
            obj = await BloodPressure.objects.acreate(
                simulation_id=simulation_id,
                min_value=min_value,                 # systolic min
                max_value=max_value,                 # systolic max
                min_value_diastolic=min_value_diastolic,
                max_value_diastolic=max_value_diastolic,
                lock_value=lock_value,
            )
            return obj

        model_map = {
            MeasurementKind.HR: HeartRate,
            MeasurementKind.SPO2: SPO2,
            MeasurementKind.ETCO2: ETCO2,
            MeasurementKind.BGL: BloodGlucoseLevel,
        }

        model = model_map[kind]
        obj = await model.objects.acreate(
            simulation_id=simulation_id,
            min_value=min_value,
            max_value=max_value,
            lock_value=lock_value,
        )
        return obj

    @strawberry_django.mutation(permission_classes=[])
    async def create_injury(
        self,
        info: strawberry.Info,
        simulation_id: ID,
        injury_category: str,
        injury_location: str,
        injury_kind: str,
        injury_description: str,
        is_treated: bool,
        parent_injury_id: Optional[ID] = None,
    ) -> InjuryType | None:
        """Create a new injury event.

        Validates enums against the model's TextChoices and optionally links a parent injury.
        Returns the created object (projected to `InjuryType`).
        """
        # Validate codes against model choices (ensures clean errors before hitting DB)
        valid_cat = {c[0] for c in Injury.InjuryCategory.choices}
        valid_loc = {l[0] for l in Injury.InjuryLocation.choices}
        valid_knd = {t[0] for t in Injury.InjuryKind.choices}

        if injury_category not in valid_cat:
            raise ValueError(f"Invalid injury_category: {injury_category}")
        if injury_location not in valid_loc:
            raise ValueError(f"Invalid injury_location: {injury_location}")
        if injury_kind not in valid_knd:
            raise ValueError(f"Invalid injury_kind: {injury_kind}")

        parent = None
        if parent_injury_id is not None:
            try:
                parent = Injury.objects.aget(pk=parent_injury_id)
            except Injury.DoesNotExist:
                raise ValueError(f"parent_injury_id not found: {parent_injury_id}")

        obj = Injury.objects.acreate(
            simulation_id=simulation_id,
            injury_category=injury_category,
            injury_location=injury_location,
            injury_kind=injury_kind,
            injury_description=injury_description,
            is_treated=is_treated,
            parent_injury=parent,
        )
        return obj