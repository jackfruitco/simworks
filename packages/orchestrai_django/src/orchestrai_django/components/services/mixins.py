# orchestrai_django/components/services/mixins.py
"""Service mixins for Django-specific context augmentation."""

import logging

__all__ = ["PreviousResponseMixin"]

from orchestrai.components.services import ServiceError

logger = logging.getLogger(__name__)


class PreviousResponseMixin:
    """
    Mixin that auto-fetches `previous_response_id` from ServiceCall.

    When a service includes this mixin and has `simulation_id` in its context,
    this mixin will automatically look up the most recent completed service call's
    OpenAI response ID and inject it into the context as `previous_response_id`.

    This enables OpenAI's Responses API multi-turn conversation feature
    without requiring callers to explicitly fetch and pass the ID.

    Usage:
        @service
        class MyReplyService(PreviousResponseMixin, ChatlabMixin, DjangoBaseService):
            ...

    Requirements:
        - `simulation_id` must be present in `self.context`

    Data Source:
        Queries ServiceCall where:
        - related_object_id matches the simulation_id
        - status is COMPLETED
        - openai_response_id is not null
        Orders by -finished_at to get the most recent.
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
            from orchestrai_django.models import ServiceCall as ServiceCallModel, CallStatus

            prev_call = await ServiceCallModel.objects.filter(
                related_object_id=str(simulation_id),
                status=CallStatus.COMPLETED,
                openai_response_id__isnull=False,
            ).order_by("-finished_at").afirst()

            if not prev_call:
                raise ValueError("No previous response found")

            prev_id = prev_call.openai_response_id
            if not prev_id:
                raise ValueError("No previous response ID found")

            self.context["previous_response_id"] = prev_id
            logger.debug("-- [context] set `previous_response_id=%s`", prev_id)
            return

        except Exception as exc:
            raise ServiceError(
                "-- [context] unable to set `previous_response_id`"
            ) from exc
