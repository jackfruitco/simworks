# simcore/schema.py
import logging

import graphene
from accounts.models import CustomUser
from chatlab.models import Message
from chatlab.models import Simulation
from chatlab.schema import MessageType
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from graphene_django.types import DjangoObjectType
from simcore.models import SimulationImage
from simcore.models import SimulationMetadata

logger = logging.getLogger(__name__)


class UserType(DjangoObjectType):
    class Meta:
        model = CustomUser
        fields = ("id", "username")


class SimulationMetadataType(DjangoObjectType):
    class Meta:
        model = SimulationMetadata
        fields = ["id", "simulation", "attribute", "key", "value"]


class SimulationType(DjangoObjectType):
    messages = graphene.List(MessageType)
    user = graphene.Field(UserType)
    metadata = graphene.List(SimulationMetadataType)
    feedback = graphene.List(SimulationMetadataType)
    is_complete = graphene.Boolean()
    is_in_progress = graphene.Boolean()
    length = graphene.Int()

    class Meta:
        model = Simulation
        fields = (
            "id",
            "start_timestamp",
            "end_timestamp",
            "time_limit",
            "diagnosis",
            "chief_complaint",
            "prompt",
        )

    def resolve_messages(self, info):
        return Message.objects.filter(simulation=self).order_by("timestamp")

    def resolve_user(self, info) -> graphene.Field:
        return self.user

    def resolve_metadata(self, info):
        return SimulationMetadata.objects.filter(simulation=self).order_by("-timestamp")

    def resolve_feedback(self, info):
        return SimulationMetadata.objects.filter(simulation=self).filter(
            attribute="feedback"
        )

    def resolve_is_complete(self, info) -> graphene.Boolean:
        return self.is_complete

    def resolve_is_in_progress(self, info) -> graphene.Boolean:
        return self.is_in_progress

    def resolve_length(self, info) -> graphene.Int:
        return self.length


class ImageVariantType(graphene.ObjectType):
    name = graphene.String()
    url = graphene.String()
    width = graphene.Int()
    height = graphene.Int()


class SimulationImageType(DjangoObjectType):
    """
    GraphQL type for handling simulation images with variant generation capabilities.
    Supports both named variants and dynamic image resizing.
    """

    # Default settings for image processing
    DEFAULT_IMAGE_FORMAT = "WEBP"  # Format used for generated image variants
    DEFAULT_IMAGE_QUALITY = 85  # Quality setting for image compression (0-100)

    variant = graphene.Field(
        ImageVariantType,
        name=graphene.String(required=False),
        width=graphene.Int(required=False),
        height=graphene.Int(required=False),
    )

    class Meta:
        model = SimulationImage
        fields = ("id", "simulation", "mime_type", "original", "description")

    def resolve_variant(self, info, name=None, width=None, height=None):
        """
        Resolves an image variant based on provided parameters.

        Args:
            info: GraphQL resolve info
            name: Optional name of the predefined variant
            width: Optional desired width of the image
            height: Optional desired height of the image

        Returns:
            dict: Image variant data including name, URL, width, and height

        Raises:
            ValueError: If invalid parameters are provided
        """
        self._validate_input_parameters(name, width, height)

        if name:
            return self._get_named_variant(name, width, height)

        return self._generate_dynamic_variant(width, height)

    def _validate_input_parameters(self, name, width, height):
        """
        Validates the input parameters for variant generation.

        Args:
            name: Variant name to validate
            width: Image width to validate
            height: Image height to validate

        Raises:
            ValueError: If parameters are missing or invalid
        """
        # At least one parameter must be provided
        if not (name or width or height):
            raise ValueError("Must specify either 'name', 'width', or 'height'")

        # Validate dimensions if provided
        if width or height:
            width = width or height
            height = height or width
            if width <= 0 or height <= 0:
                raise ValueError("Width and height must be positive integers.")

    def _get_named_variant(self, name, width, height):
        """
        Retrieves a predefined named variant of the image.

        Args:
            name: Name of the variant to retrieve
            width: Fallback width if variant not found
            height: Fallback height if variant not found

        Returns:
            dict: Variant information if found
            None: If variant is not found and fallback to dynamic generation is possible

        Raises:
            ValueError: If a variant is not found, and no fallback dimensions are provided
        """
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
        """
        Generates a dynamic variant of the image with specified dimensions.

        Args:
            width: Desired width of the variant
            height: Desired height of the variant

        Returns:
            dict: Generated variant information including name, URL, width, and height
        """
        from imagekit.specs import ImageSpec
        from pilkit.processors import ResizeToFill

        # Ensure both dimensions are set
        width = width or height
        height = height or width

        # Generate unique names for the variant
        variant_name = f"variant_{width}x{height}"
        cache_filename = (
            f"{self.uuid}_{variant_name}.{self.DEFAULT_IMAGE_FORMAT.lower()}"
        )

        # Create and configure the image specification
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


class Query(graphene.ObjectType):

    simulation = graphene.Field(SimulationType, id=graphene.Int(required=True))
    simulations = graphene.List(SimulationType)

    simulation_image = graphene.Field(
        SimulationImageType, id=graphene.Int(required=True)
    )

    simulation_images = graphene.List(
        SimulationImageType,
        ids=graphene.List(graphene.Int),
        simulation=graphene.Int(),
        limit=graphene.Int(),
    )

    def resolve_simulation(self, info, id):
        return get_object_or_404(Simulation, id=id)

    def resolve_simulations(self, info):
        return Simulation.objects.all()

    def resolve_simulation_image(self, info, id):
        return get_object_or_404(SimulationImage, id=id)

    def resolve_simulation_images(
        self, info, ids=None, simulation=None, limit=None
    ) -> QuerySet[SimulationImage]:
        """
        Return simulation images, optionally filtered by image IDs and simulation(s).

        Args:
            ids: Optional list of SimulationImage IDs to include.
            simulation: A single simulation ID or list of IDs.
            limit: Max number of messages to return.

        Returns:
            QuerySet of SimulationImage objects.
        """
        qs = SimulationImage.objects.all()

        # Filter by image IDs, if provided.
        if ids:
            if not isinstance(ids, list):
                ids = [ids]
            qs = qs.filter(id__in=ids)

        # Filter by simulation(s), if provided.
        if simulation:
            if not isinstance(simulation, list):
                simulation = [simulation]
            qs = qs.filter(simulation_id__in=simulation)

        # Limit the number of messages returned, if provided.
        if limit:
            qs = qs[:limit]
        return qs


class Mutation(graphene.ObjectType):
    pass
