"""Base class for persistence handler components.

Simplified for Pydantic AI - no identity system required.
"""

from abc import ABC, abstractmethod
from typing import Any


class BasePersistenceHandler(ABC):
    """
    Base class for persistence handlers.

    Persistence handlers map Pydantic AI response data to Django domain models.
    No identity system - handlers are registered by their schema class.

    Example:
        @persistence_handler
        class PatientInitialPersistence(BasePersistenceHandler):
            schema = PatientInitialOutputSchema

            async def persist(self, *, data, context) -> Message:
                # data is the validated Pydantic model instance
                message = await Message.objects.acreate(
                    simulation_id=context["simulation_id"],
                    content=data.messages[0].text,
                )
                return message
    """

    # Schema class this handler processes (required)
    schema: type | None = None

    @abstractmethod
    async def persist(self, *, data: Any, context: dict[str, Any]) -> Any:
        """
        Persist response data to domain models.

        Args:
            data: Validated Pydantic model instance (or dict)
            context: Execution context with simulation_id, user_id, etc.

        Returns:
            Primary domain object created (e.g., Message instance)
        """
        ...

    def _schema_key(self) -> str:
        """Get the schema key for idempotency tracking."""
        if self.schema is None:
            return ""
        return f"{self.schema.__module__}.{self.schema.__name__}"

    async def ensure_idempotent(self, *, call_id: str, context: dict[str, Any]):
        """
        Ensure idempotent persistence using PersistedChunk tracking.

        Args:
            call_id: Unique identifier for this service call
            context: Execution context

        Returns:
            tuple: (chunk: PersistedChunk, created: bool)
                - chunk: The PersistedChunk record (existing or new)
                - created: True if this is first persistence, False if already done

        Example:
            async def persist(self, *, data, context) -> Message:
                call_id = context.get("call_id", "")
                chunk, created = await self.ensure_idempotent(
                    call_id=call_id, context=context
                )

                if not created and chunk.object_id:
                    # Already persisted - return existing
                    return await Message.objects.aget(id=chunk.object_id)

                # First persistence - create domain objects
                message = await Message.objects.acreate(...)

                # Link to tracking record
                from django.contrib.contenttypes.models import ContentType
                chunk.content_type = await ContentType.objects.aget_for_model(Message)
                chunk.object_id = message.id
                await chunk.asave()

                return message
        """
        from orchestrai_django.models import PersistedChunk

        schema_key = self._schema_key()

        chunk, created = await PersistedChunk.objects.aget_or_create(
            call_id=call_id,
            schema_identity=schema_key,
            defaults={
                "namespace": context.get("namespace", ""),
                "handler_identity": f"{self.__class__.__module__}.{self.__class__.__name__}",
            },
        )

        return chunk, created
