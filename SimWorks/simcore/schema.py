import logging

import strawberry
from strawberry import auto
from strawberry.django import type
from strawberry.types import Info
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404

from accounts.models import CustomUser
from chatlab.models import Message, Simulation
from chatlab.schema import MessageType
from simcore.models import SimulationImage, SimulationMetadata

logger = logging.getLogger(__name__)


@type(CustomUser)
class UserType:
    id: auto
    username: auto


@type(SimulationMetadata)
class SimulationMetadataType:
    id: auto
    simulation: auto
    attribute: auto
    key: auto
    value: auto


@type(Simulation)
class SimulationType:
    id: auto
    start_timestamp: auto
    end_timestamp: auto
    time_limit: auto
    diagnosis: auto
    chief_complaint: auto
    prompt: auto

    @strawberry.field
    def messages(self) -> list[MessageType]:
        return list(Message.objects.filter(simulation=self).order_by("timestamp"))

    @strawberry.field
    def user(self) -> UserType:
        return self.user  # type: ignore[attr-defined]

    @strawberry.field
    def metadata(self) -> list[SimulationMetadataType]:
        return list(
            SimulationMetadata.objects.filter(simulation=self).order_by("-timestamp")
        )

    @strawberry.field
    def feedback(self) -> list[SimulationMetadataType]:
        return list(
            SimulationMetadata.objects.filter(simulation=self, attribute="feedback")
        )

    @strawberry.field
    def is_complete(self) -> bool:
        return self.is_complete  # type: ignore[attr-defined]

    @strawberry.field
    def is_in_progress(self) -> bool:
        return self.is_in_progress  # type: ignore[attr-defined]

    @strawberry.field
    def length(self) -> int:
        return self.length  # type: ignore[attr-defined]


@strawberry.type
class ImageVariantType:
    name: str
    url: str
    width: int
    height: int


@type(SimulationImage)
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
        info: Info,
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
class Query:
    @strawberry.field
    def simulation(self, info: Info, id: int) -> SimulationType:
        return get_object_or_404(Simulation, id=id)

    @strawberry.field
    def simulations(self, info: Info) -> list[SimulationType]:
        return list(Simulation.objects.all())

    @strawberry.field
    def simulation_image(self, info: Info, id: int) -> SimulationImageType:
        return get_object_or_404(SimulationImage, id=id)

    @strawberry.field
    def simulation_images(
        self,
        info: Info,
        ids: list[int] | None = None,
        simulation: list[int] | None = None,
        limit: int | None = None,
    ) -> list[SimulationImageType]:
        qs: QuerySet[SimulationImage] = SimulationImage.objects.all()
        if ids:
            if not isinstance(ids, list):
                ids = [ids]
            qs = qs.filter(id__in=ids)
        if simulation:
            if not isinstance(simulation, list):
                simulation = [simulation]
            qs = qs.filter(simulation_id__in=simulation)
        if limit:
            qs = qs[:limit]
        return list(qs)


@strawberry.type
class Mutation:
    pass

