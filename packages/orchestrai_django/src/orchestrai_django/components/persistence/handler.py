"""Base class for persistence handler components."""

from typing import Any
from orchestrai_django.identity.mixins import DjangoIdentityMixin
from orchestrai.components import BaseComponent
from abc import ABC
from orchestrai.components.schemas import BaseOutputSchema
from orchestrai.types import Response


class BasePersistenceHandler(DjangoIdentityMixin, BaseComponent, ABC):
    """
    Base class for persistence handler components.

    Persistence handlers map structured response schemas to Django domain models.
    They are discovered from app/orca/persist/ directories and registered by
    (namespace, schema_identity) for routing.

    Identity:
        Domain: "persist"
        Namespace: From mixin (e.g., "chatlab", "trainerlab")
        Group: From mixin (e.g., "standardized_patient", "feedback")
        Name: Class name

    Example:
        @persistence_handler
        class PatientInitialPersistence(ChatlabMixin, StandardizedPatientMixin, BasePersistenceHandler):
            schema = PatientInitialOutputSchema

            async def persist(self, response: Response) -> Message:
                # Extract structured_data
                data = self.schema.model_validate(response.structured_data)

                # Create domain objects
                message = await Message.objects.acreate(
                    simulation_id=response.context["simulation_id"],
                    content=...,
                )

                return message
    """

    domain = "persist"

    # Schema this handler processes (must be set by subclass)
    schema: type[BaseOutputSchema] | None = None

    async def persist(self, response: Response) -> Any:
        """
        Persist response structured data to domain models.

        This method must be implemented by subclasses to map the specific
        schema structure to the appropriate Django models.

        Args:
            response: Full Response object with:
                - structured_data: Validated schema instance
                - context: Service context (simulation_id, user_id, etc.)
                - execution_metadata: Service identity, schema identity, etc.

        Returns:
            Primary domain object created (e.g., Message instance)

        Raises:
            ValueError: If required context fields are missing
            ValidationError: If data doesn't match expected structure
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement persist() method"
        )

    async def ensure_idempotent(self, response: Response):
        """
        Ensure idempotent persistence using PersistedChunk tracking.

        This method provides a reusable pattern for handlers to check if
        a chunk has already been persisted and retrieve the existing object.

        Returns:
            tuple: (chunk: PersistedChunk, created: bool)
                - chunk: The PersistedChunk record (existing or new)
                - created: True if this is first persistence, False if already done

        Example:
            async def persist(self, response: Response) -> Message:
                chunk, created = await self.ensure_idempotent(response)

                if not created and chunk.domain_object:
                    # Already persisted - return existing
                    return chunk.domain_object

                # First persistence - create domain objects
                message = await Message.objects.acreate(...)

                # Link to tracking record
                from django.contrib.contenttypes.models import ContentType
                chunk.content_type = ContentType.objects.get_for_model(Message)
                chunk.object_id = message.id
                await chunk.asave()

                return message
        """
        from orchestrai_django.models import PersistedChunk

        # Extract identifiers from response
        call_id = str(response.context.get("call_id") or response.correlation_id)
        schema_id = response.execution_metadata.get("schema_identity", "")

        if not schema_id:
            # Fallback to schema class if metadata missing
            if self.schema and hasattr(self.schema, "identity"):
                schema_id = self.schema.identity.as_str

        # Get or create tracking record
        chunk, created = await PersistedChunk.objects.aget_or_create(
            call_id=call_id,
            schema_identity=schema_id,
            defaults={
                "namespace": response.namespace or "",
                "handler_identity": self.identity.as_str,
            },
        )

        return chunk, created
