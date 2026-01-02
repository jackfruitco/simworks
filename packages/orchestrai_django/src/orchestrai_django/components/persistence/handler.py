"""Base class for persistence handler components."""

from typing import Any
from orchestrai_django.identity.mixins import DjangoIdentityMixin
from orchestrai.components.schemas import BaseOutputSchema
from orchestrai.types import Response


class BasePersistenceHandler(DjangoIdentityMixin):
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
