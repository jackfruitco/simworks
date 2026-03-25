"""Guard framework models for presence tracking and usage accounting."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from .enums import (
    ClientVisibility,
    GuardState,
    LabType,
    PauseReason,
    UsageScopeType,
)


class SessionPresence(models.Model):
    """Per-simulation presence tracking and guard state.

    One row per simulation. Created when a lab session starts.
    The server is authoritative for guard_state transitions — clients
    may show optimistic warnings but the backend decides actual state.
    """

    simulation = models.OneToOneField(
        "simcore.Simulation",
        on_delete=models.CASCADE,
        related_name="guard_presence",
    )
    lab_type = models.CharField(max_length=16, choices=LabType.choices)
    guard_state = models.CharField(
        max_length=32,
        choices=GuardState.choices,
        default=GuardState.ACTIVE,
    )
    pause_reason = models.CharField(
        max_length=32,
        choices=PauseReason.choices,
        default=PauseReason.NONE,
    )

    # Presence fields — updated by client heartbeats.
    last_presence_at = models.DateTimeField(null=True, blank=True)
    client_visibility = models.CharField(
        max_length=16,
        choices=ClientVisibility.choices,
        default=ClientVisibility.UNKNOWN,
    )
    last_visibility_change_at = models.DateTimeField(null=True, blank=True)

    # Guard transition timestamps.
    paused_at = models.DateTimeField(null=True, blank=True)
    runtime_locked_at = models.DateTimeField(null=True, blank=True)
    warning_sent_at = models.DateTimeField(null=True, blank=True)

    # Wall-clock bounds.
    wall_clock_started_at = models.DateTimeField(null=True, blank=True)
    wall_clock_expires_at = models.DateTimeField(null=True, blank=True)

    # Convenience flag derived from guard_state.  Denormalized for cheap
    # SELECT … WHERE engine_runnable = True queries.
    engine_runnable = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["guard_state", "last_presence_at"],
                name="idx_guard_state_presence",
            ),
            models.Index(
                fields=["lab_type", "guard_state"],
                name="idx_guard_lab_state",
            ),
            models.Index(
                fields=["engine_runnable"],
                name="idx_guard_engine_runnable",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"SessionPresence(sim={self.simulation_id}, "
            f"state={self.guard_state}, runnable={self.engine_runnable})"
        )


class UsageRecord(models.Model):
    """Aggregated token/call usage per scope.

    Rows are upserted (incremented) after each completed service call.
    Supports querying by session, user, account, lab, product, and time period.

    The schema deliberately avoids coupling to a specific billing model so that
    future "included quota + extra purchased quota" logic can layer on top.
    """

    scope_type = models.CharField(max_length=16, choices=UsageScopeType.choices)

    # Polymorphic scope references — exactly one is non-null per row.
    simulation = models.ForeignKey(
        "simcore.Simulation",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="usage_records",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="usage_records",
    )
    account = models.ForeignKey(
        "accounts.Account",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="usage_records",
    )

    lab_type = models.CharField(max_length=16, choices=LabType.choices)
    product_code = models.CharField(max_length=64, blank=True, default="")
    period_start = models.DateTimeField()
    period_end = models.DateTimeField(null=True, blank=True)

    # Token counters.
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    reasoning_tokens = models.PositiveBigIntegerField(default=0)
    total_tokens = models.PositiveBigIntegerField(default=0)

    service_call_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["scope_type", "simulation_id"],
                name="idx_usage_scope_sim",
            ),
            models.Index(
                fields=["scope_type", "user_id", "period_start"],
                name="idx_usage_scope_user",
            ),
            models.Index(
                fields=["scope_type", "account_id", "period_start"],
                name="idx_usage_scope_account",
            ),
            models.Index(
                fields=["lab_type", "product_code"],
                name="idx_usage_lab_product",
            ),
        ]
        constraints = [
            # One aggregate row per session per period.
            models.UniqueConstraint(
                fields=["scope_type", "simulation_id", "lab_type", "product_code", "period_start"],
                condition=models.Q(scope_type="session"),
                name="uniq_usage_session",
            ),
            # One aggregate row per user per period.
            models.UniqueConstraint(
                fields=["scope_type", "user_id", "lab_type", "product_code", "period_start"],
                condition=models.Q(scope_type="user"),
                name="uniq_usage_user",
            ),
            # One aggregate row per account per period.
            models.UniqueConstraint(
                fields=["scope_type", "account_id", "lab_type", "product_code", "period_start"],
                condition=models.Q(scope_type="account"),
                name="uniq_usage_account",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"UsageRecord(scope={self.scope_type}, lab={self.lab_type}, tokens={self.total_tokens})"
        )
