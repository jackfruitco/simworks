# orchestrai_django/models/mixins.py
from collections.abc import Iterable, Mapping
import contextlib
from typing import Any, Self
import uuid
import warnings

from channels.db import database_sync_to_async
from django.db import models
from django.utils import timezone


class PersistModel(models.Model):
    """
    Async-first persistence helpers for all SimWorks models.
    """

    class Meta:
        abstract = True

    # -------- field utilities --------
    @classmethod
    def _field_names(cls) -> set[str]:
        return {f.name for f in cls._meta.get_fields() if getattr(f, "concrete", True)}

    @classmethod
    def _translate_payload(
        cls,
        data: Mapping[str, Any],
        translate_keys: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        if not translate_keys:
            return dict(data)
        out: dict[str, Any] = {}
        for k, v in data.items():
            dest = translate_keys.get(k, k)
            out[dest] = v
        return out

    # -------- async persistence API --------
    async def apersist(
        self: Self,
        data: Mapping[str, Any] | None = None,
        *,
        translate_keys: Mapping[str, str] | None = None,
        update_fields: Iterable[str] | None = None,
        using: str | None = None,
        clean: bool = True,
        make_aware: bool = True,
    ) -> Self:
        """
        Update self from 'data' and save. Safe to call from async code.
        """
        payload = self._translate_payload(data or {}, translate_keys)
        valid_fields = self._field_names()

        # normalize datetimes (optional)
        if make_aware:
            for k, v in list(payload.items()):
                if hasattr(v, "tzinfo") and getattr(v, "tzinfo", None) is None:
                    with contextlib.suppress(Exception):
                        payload[k] = timezone.make_aware(v, timezone.get_current_timezone())

        # set attributes (ignore unknowns, but log them)
        unknown: list[str] = []
        for k, v in payload.items():
            if k in valid_fields:
                setattr(self, k, v)
            else:
                unknown.append(k)

        if unknown:
            # keep this mild; unknown keys are common when schemas evolve
            from logging import getLogger

            getLogger(__name__).debug(
                "Ignoring unknown fields for %s: %s", self.__class__.__name__, ", ".join(unknown)
            )

        @database_sync_to_async
        def _save_sync() -> None:
            if clean and hasattr(self, "full_clean"):
                self.full_clean()
            if update_fields:
                self.save(using=using, update_fields=list(update_fields))
            else:
                self.save(using=using)

        await _save_sync()
        return self

    # -------- convenience classmethods --------
    @classmethod
    async def acreate_from(
        cls,
        data: Mapping[str, Any],
        *,
        translate_keys: Mapping[str, str] | None = None,
        using: str | None = None,
        clean: bool = True,
    ) -> Self:
        obj = cls()  # type: ignore[call-arg]
        return await obj.aperist(data, translate_keys=translate_keys, using=using, clean=clean)

    # small typo guard: keep both spellings just in case muscle memory kicks in :)
    async def aperist(self, *a, **kw):  # pragma: no cover
        return await self.apersist(*a, **kw)

    @classmethod
    async def aupdate_or_create_from(
        cls,
        *,
        lookup: Mapping[str, Any],
        data: Mapping[str, Any],
        translate_keys: Mapping[str, str] | None = None,
        using: str | None = None,
        clean: bool = True,
    ) -> Self:
        """
        Async upsert: find by 'lookup', apply 'data', save.
        """
        from django.db.models import Q

        @database_sync_to_async
        def _get_or_create():
            q = Q()
            for k, v in lookup.items():
                q &= Q(**{k: v})
            obj = cls._default_manager.using(using).filter(q).first()
            created = False
            if obj is None:
                obj = cls()  # type: ignore
                created = True
            return obj, created

        obj, _ = await _get_or_create()
        return await obj.apersist(data, translate_keys=translate_keys, using=using, clean=clean)


class ApiAccessControl(models.Model):
    """Dummy Model to create API permissions"""

    class Meta:
        permissions = [
            ("read_api", "Can read API"),
            ("write_api", "Can write API"),
        ]


class OutboxEvent(models.Model):
    """Outbox pattern for durable event delivery.

    Events are created atomically with domain changes, then delivered
    asynchronously by a drain worker. This ensures at-least-once delivery
    even if the WebSocket connection drops or the server restarts.

    Flow:
    1. Domain operation creates OutboxEvent in same transaction
    2. Drain worker (periodic + immediate poke) picks up pending events
    3. Events are delivered to WebSocket channel layer
    4. delivered_at is set on successful delivery

    Idempotency:
    - idempotency_key ensures duplicate events are not created
    - Clients should deduplicate by event_id
    """

    warnings.warn(
        "`common.models.OutboxEvent` is deprecated. Use the `orchestrai-django` models instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    class EventStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique event ID, also used as cursor for pagination",
    )

    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
        help_text="Unique key to prevent duplicate events (e.g., 'message.created:{message_id}')",
    )

    event_type = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Event type (e.g., 'message.created', 'simulation.ended')",
    )

    payload = models.JSONField(
        help_text="Event payload as JSON",
    )

    simulation_id = models.PositiveBigIntegerField(
        db_index=True,
        help_text="Simulation ID for routing to correct WebSocket group",
    )

    correlation_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Request correlation ID for tracing",
    )

    status = models.CharField(
        max_length=20,
        choices=EventStatus.choices,
        default=EventStatus.PENDING,
        db_index=True,
        help_text="Current delivery status",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="When the event was created",
    )

    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When the event was successfully delivered",
    )

    delivery_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Number of delivery attempts",
    )

    last_error = models.TextField(
        null=True,
        blank=True,
        help_text="Last delivery error message",
    )

    class Meta:
        ordering = ["created_at"]
        indexes = [
            # For drain worker: find pending events efficiently
            models.Index(
                fields=["status", "created_at"],
                name="outbox_status_created_idx",
            ),
            # For catch-up queries: events for a simulation after a cursor
            models.Index(
                fields=["simulation_id", "created_at"],
                name="outbox_sim_created_idx",
            ),
            # For cleanup: find old delivered events
            models.Index(
                fields=["delivered_at"],
                name="outbox_delivered_idx",
                condition=models.Q(delivered_at__isnull=False),
            ),
        ]
        verbose_name = "Outbox Event"
        verbose_name_plural = "Outbox Events"

    def __str__(self) -> str:
        return f"OutboxEvent {self.id} ({self.event_type}) - {self.status}"

    def mark_delivered(self) -> None:
        """Mark event as successfully delivered."""
        self.status = self.EventStatus.DELIVERED
        self.delivered_at = timezone.now()
        self.save(update_fields=["status", "delivered_at"])

    def mark_failed(self, error: str) -> None:
        """Mark event as failed with error message."""
        self.status = self.EventStatus.FAILED
        self.delivery_attempts += 1
        self.last_error = error
        self.save(update_fields=["status", "delivery_attempts", "last_error"])

    def increment_attempts(self) -> None:
        """Increment delivery attempts without changing status."""
        self.delivery_attempts += 1
        self.save(update_fields=["delivery_attempts"])
