# orchestrai_django/components/services/mixins.py
"""Service mixins for Django-specific context augmentation."""

import logging

from asgiref.sync import sync_to_async

__all__ = ["PreviousResponseMixin"]

from orchestrai.components.services import ServiceError

logger = logging.getLogger(__name__)


class PreviousResponseMixin:
    """
    Mixin that auto-fetches `previous_response_id` from the simulation.

    When a service includes this mixin and has `simulation_id` in its context,
    this mixin will automatically look up the most recent AI response's
    provider ID and inject it into the context as `previous_response_id`.

    This enables OpenAI's Responses API multi-turn conversation feature
    without requiring callers to explicitly fetch and pass the ID.

    Usage:
        @service
        class MyReplyService(PreviousResponseMixin, ChatlabMixin, DjangoBaseService):
            ...

    Requirements:
        - `simulation_id` must be present in `self.context`
        - The Simulation model must have `aget_previous_response_id()` method
    """

    async def _aprepare_context(self) -> None:
        """Fetch and inject previous_response_id if simulation_id is in context."""
        # Call parent hook if it exists (for mixin chaining)
        if hasattr(super(), "_aprepare_context"):
            await super()._aprepare_context()

        # Skip if already set (allows explicit override)
        if self.context.get("previous_response_id") is not None:
            return

        simulation_id = self.context.get("simulation_id")
        if simulation_id is None:
            return

        try:
            from simulation.models import Simulation

            # Resolve simulation, then, try to
            # fetch previous response ID from it.
            # Otherwise, raise ValueError.
            simulation = await sync_to_async(Simulation.resolve, thread_sensitive=False)(simulation_id)

            prev_id = await simulation.aget_previous_response_id()
            if not prev_id: raise ValueError("No previous response found")

            self.context["previous_response_id"] = prev_id
            logger.debug("-- ✅ [context] set `previous_response_id=%s`", prev_id)
            return

        except Exception as exc:
            raise ServiceError(
                "-- ❌ [context] unable to set `previous_response_id`"
            ) from exc
