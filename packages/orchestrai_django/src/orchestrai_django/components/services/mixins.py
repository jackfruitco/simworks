# orchestrai_django/components/services/mixins.py
"""Service mixins for Django-specific context augmentation."""

import logging

__all__ = ["PreviousResponseMixin"]

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
        - service_identity matches the current service (when available)
        - status is COMPLETED
        - provider_response_id is not null
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

            service_identity = getattr(getattr(self, "identity", None), "as_str", None)
            filters = {
                "related_object_id": str(simulation_id),
                "status": CallStatus.COMPLETED,
                "provider_response_id__isnull": False,
            }
            if service_identity:
                filters["service_identity"] = service_identity

            prev_call = await ServiceCallModel.objects.filter(
                **filters,
            ).order_by("-finished_at").afirst()

            if not prev_call:
                logger.debug("-- [context] no previous response for simulation_id=%s", simulation_id)
                return

            prev_id = prev_call.provider_response_id
            if not prev_id:
                logger.debug("-- [context] previous response ID missing for simulation_id=%s", simulation_id)
                return

            self.context["previous_response_id"] = prev_id
            self.context["previous_provider_response_id"] = prev_id
            logger.debug("-- [context] set `previous_response_id=%s`", prev_id)
            return

        except Exception as exc:
            logger.warning(
                "-- [context] unable to set `previous_response_id`: %s",
                exc,
                exc_info=True,
            )
            return
