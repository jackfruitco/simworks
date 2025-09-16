import logging

import strawberry
import strawberry_django
from django.db.models import QuerySet
from strawberry import auto

from accounts.schema import UserType
from chatlab.schema import MessageType
from simcore.models import Simulation
from simcore.models import (
    SimulationImage,
    SimulationMetadata
)

logger = logging.getLogger(__name__)


@strawberry_django.type(SimulationMetadata)
class SimulationMetadataType:
    id: auto
    simulation: auto
    key: auto
    value: auto

    created_at: auto
    modified_at: auto


@strawberry_django.type(Simulation)
class SimulationType:
    id: auto
    openai_model: auto
    diagnosis: auto

    chief_complaint: auto
    metadata_checksum: auto
    sim_patient_full_name: auto
    sim_patient_display_name: auto

    prompt: auto
    user: UserType
    messages: list[MessageType]
    metadata: list[SimulationMetadataType]
    is_complete: auto
    is_in_progress: auto

    @strawberry.field
    def start_timestamp_ms(self) -> int:
        return int(getattr(self, "start_timestamp_ms", 0))

    @strawberry.field
    def end_timestamp_ms(self) -> int:
        return int(getattr(self, "end_timestamp_ms", 0))

    @strawberry.field
    def time_limit_ms(self) -> int:
        return int(getattr(self, "time_limit_ms", 0))

    @strawberry.field
    def length(self) -> int:
        delta = getattr(self, "length", None)
        return int(delta.total_seconds() * 1000) if delta else 0


@strawberry.type
class ImageVariantType:
    name: str
    url: str
    width: int
    height: int


@strawberry_django.type(SimulationImage)
class SimulationImageType:
    id: auto
    simulation: auto
    mime_type: auto
    original: auto
    description: auto

    DEFAULT_IMAGE_FORMAT = "WEBP"
    DEFAULT_IMAGE_QUALITY = 85

    @strawberry.field
    def variant(
        self,
        info: strawberry.Info,
        name: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> ImageVariantType | None:
        self._validate_input_parameters(name, width, height)

        if name:
            variant = self._get_named_variant(name, width, height)
            if variant:
                return ImageVariantType(**variant)

        generated = self._generate_dynamic_variant(width, height)
        if generated:
            return ImageVariantType(**generated)
        return None

    def _validate_input_parameters(self, name, width, height):
        if not (name or width or height):
            raise ValueError("Must specify either 'name', 'width', or 'height'")
        if width or height:
            width = width or height
            height = height or width
            if width <= 0 or height <= 0:
                raise ValueError("Width and height must be positive integers.")

    def _get_named_variant(self, name, width, height):
        try:
            spec_file = getattr(self, name)
            return {
                "name": name,
                "url": spec_file.url,
                "width": spec_file.width,
                "height": spec_file.height,
            }
        except AttributeError:
            if not (width or height):
                raise ValueError(
                    f"Variant '{name}' not found, and no width/height provided to generate a fallback."
                )
            logger.warning(
                f"Variant '{name}' not found. Falling back to dynamic generation."
            )
            return None

    def _generate_dynamic_variant(self, width, height):
        if not (width or height):
            return None

        from imagekit.specs import ImageSpec
        from pilkit.processors import ResizeToFill

        width = width or height
        height = height or width

        variant_name = f"variant_{width}x{height}"
        cache_filename = f"{self.uuid}_{variant_name}.{self.DEFAULT_IMAGE_FORMAT.lower()}"

        spec = ImageSpec(
            source=self.original,
            processors=[ResizeToFill(width, height)],
            format=self.DEFAULT_IMAGE_FORMAT,
            options={"quality": self.DEFAULT_IMAGE_QUALITY},
        )
        file = spec.generate()
        file.name = cache_filename

        return {
            "name": variant_name,
            "url": spec.storage.url(file.name),
            "width": width,
            "height": height,
        }


@strawberry.type
class SuccessPayload:
    success: bool
    message: str


@strawberry.type
class SimCoreQuery:
    @strawberry_django.field
    def simulation(self, info: strawberry.Info, _id: strawberry.ID) -> SimulationType or Simulation:
        return (
            Simulation.objects
            .select_related("user")
            .get(id=_id)
        )

    @strawberry_django.field
    def simulations(self, info: strawberry.Info, _ids: list[strawberry.ID] | None = None) -> list[SimulationType]:
        qs = Simulation.objects.select_related("user").all()
        if _ids:
            qs = qs.filter(id__in=_ids)
        return qs

    @strawberry_django.field
    def simulation_image(self, info: strawberry.Info, _id: strawberry.ID) -> SimulationImageType | None:
        try:
            return SimulationImage.objects.select_related("simulation").get(id=_id)
        except SimulationImage.DoesNotExist:
            return None

    @strawberry_django.field
    def simulation_images(
        self,
        info: strawberry.Info,
        ids: list[int] | None = None,
        simulation: list[int] | None = None,
        limit: int | None = None,
    ) -> list[SimulationImageType]:
        qs: QuerySet[SimulationImage] = SimulationImage.objects.select_related("simulation").all()
        if ids:
            qs = qs.filter(id__in=ids)
        if simulation:
            qs = qs.filter(simulation_id__in=simulation)
        if limit:
            qs = qs[:limit]
        return qs


@strawberry.type
class SimCoreMutation:
    @strawberry_django.mutation(permission_classes=[])
    def end_simulation(self, _id: strawberry.ID) -> SuccessPayload:
        try:
            s = Simulation.objects.get(id=_id)
            if s.is_in_progress:
                s.end()
                return SuccessPayload(success=True, message="Simulation ended")
            return SuccessPayload(success=False, message="Simulation was not in progress")
        except Simulation.DoesNotExist:
            return SuccessPayload(success=False, message=f"No simulation with id {_id}")
