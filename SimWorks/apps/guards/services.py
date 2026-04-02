"""Guard service functions.

This module contains all guard state-mutation logic.  It is the only
module that writes to ``SessionPresence`` and ``UsageRecord``.

Key entry points:

* ``ensure_session_presence()`` — create/get presence row on session start.
* ``record_heartbeat()`` — update presence from client heartbeat.
* ``guard_service_entry()`` — **single shared entrypoint** for runtime calls.
* ``check_pre_session_budget()`` — TrainerLab admission check.
* ``check_chat_send_allowed()`` — ChatLab send-lock check.
* ``evaluate_inactivity()`` — server-side inactivity evaluation.
* ``evaluate_runtime_cap()`` — runtime cap evaluation.
* ``evaluate_wall_clock()`` — wall-clock expiry evaluation.
* ``record_usage()`` — increment usage counters after a service call.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from config.logging import get_logger

from .decisions import GuardDecision, RuntimeGuard
from .enums import (
    NON_RUNNABLE_STATES,
    ClientVisibility,
    DenialReason,
    GuardState,
    LabType,
    PauseReason,
    UsageScopeType,
)
from .models import SessionPresence, UsageRecord
from .policy import GuardPolicy, resolve_policy, resolve_policy_for_simulation

logger = get_logger(__name__)


# ───────────────────────────────────────────────────────────────────────
# Session presence lifecycle
# ───────────────────────────────────────────────────────────────────────


def ensure_session_presence(
    simulation_id: int,
    lab_type: str,
    *,
    wall_clock_expiry_seconds: int | None = None,
    policy: GuardPolicy | None = None,
) -> SessionPresence:
    """Get or create a ``SessionPresence`` row for a simulation.

    Called once when a lab session is started.
    """
    from apps.simcore.models import Simulation

    now = timezone.now()
    simulation = Simulation.objects.get(pk=simulation_id)

    if policy is None:
        _, _, policy = resolve_policy_for_simulation(simulation)

    expiry_seconds = wall_clock_expiry_seconds or policy.wall_clock_expiry_seconds
    expires_at = now + timedelta(seconds=expiry_seconds) if expiry_seconds else None

    presence, created = SessionPresence.objects.get_or_create(
        simulation_id=simulation_id,
        defaults={
            "lab_type": lab_type,
            "guard_state": GuardState.ACTIVE,
            "last_presence_at": now,
            "wall_clock_started_at": now,
            "wall_clock_expires_at": expires_at,
            "engine_runnable": True,
        },
    )
    if created:
        logger.info(
            "guards.presence.created",
            simulation_id=simulation_id,
            lab_type=lab_type,
        )
    return presence


def record_heartbeat(
    simulation_id: int,
    client_visibility: str = ClientVisibility.UNKNOWN,
) -> SessionPresence:
    """Record a client heartbeat and potentially clear warning state.

    This is the primary way clients report presence.  The server uses
    ``last_presence_at`` freshness to drive inactivity decisions.
    """
    now = timezone.now()
    valid_visibility = (
        client_visibility
        if client_visibility in ClientVisibility.values
        else ClientVisibility.UNKNOWN
    )

    with transaction.atomic():
        presence = SessionPresence.objects.select_for_update().get(
            simulation_id=simulation_id,
        )

        old_visibility = presence.client_visibility
        presence.last_presence_at = now
        presence.client_visibility = valid_visibility

        if old_visibility != valid_visibility:
            presence.last_visibility_change_at = now

        # A fresh heartbeat clears the WARNING state back to ACTIVE.
        if presence.guard_state == GuardState.WARNING:
            presence.guard_state = GuardState.ACTIVE
            presence.warning_sent_at = None
            presence.engine_runnable = True
            logger.info(
                "guards.warning_cleared",
                simulation_id=simulation_id,
            )

        update_fields = [
            "last_presence_at",
            "client_visibility",
            "last_visibility_change_at",
            "guard_state",
            "warning_sent_at",
            "engine_runnable",
            "modified_at",
        ]
        presence.save(update_fields=update_fields)

    return presence


# ───────────────────────────────────────────────────────────────────────
# Guard service entry — the single shared entrypoint
# ───────────────────────────────────────────────────────────────────────


def guard_service_entry(
    simulation_id: int,
    *,
    active_elapsed: int = 0,
) -> GuardDecision:
    """Single shared guard entrypoint used by all runtime / Orca calls.

    Every relevant service call must pass through this function before
    starting new AI / runtime work.  It checks:

    1. Guard state (paused / locked / ended → deny)
    2. Runtime cap (active elapsed exceeded → deny + transition state)
    3. Wall-clock expiry
    4. Usage limits

    Returns a ``GuardDecision``.
    """
    try:
        presence = SessionPresence.objects.select_related("simulation").get(
            simulation_id=simulation_id,
        )
    except SessionPresence.DoesNotExist:
        # No presence row ⇒ guard framework not initialized for this session.
        # Allow the call to proceed (backwards-compatible default).
        return GuardDecision.allow()

    _, _, policy = resolve_policy_for_simulation(presence.simulation)
    guard = RuntimeGuard(presence, policy)

    decision = guard.may_start_runtime_operation(active_elapsed)
    if not decision.allowed:
        # If runtime cap just hit, transition state.
        if decision.denial_reason == DenialReason.RUNTIME_CAP_REACHED:
            _transition_to_runtime_cap_paused(presence)
        return decision

    # Check usage limits.
    usage_snapshot = get_usage_snapshot(
        simulation_id=simulation_id,
        user_id=presence.simulation.user_id,
        account_id=presence.simulation.account_id,
    )
    usage_decision = guard.check_usage_limits(usage_snapshot)
    if not usage_decision.allowed:
        return usage_decision

    return decision


# ───────────────────────────────────────────────────────────────────────
# Inactivity evaluation (called by periodic task)
# ───────────────────────────────────────────────────────────────────────


def evaluate_inactivity(simulation_id: int) -> GuardState | None:
    """Evaluate inactivity for a session and transition state if needed.

    Returns the new ``GuardState`` if a transition occurred, ``None`` otherwise.
    """
    now = timezone.now()

    with transaction.atomic():
        try:
            presence = SessionPresence.objects.select_for_update().get(
                simulation_id=simulation_id,
            )
        except SessionPresence.DoesNotExist:
            return None

        # Only evaluate inactivity for active/idle/warning TrainerLab sessions.
        if presence.lab_type != LabType.TRAINERLAB:
            return None
        if presence.guard_state not in {
            GuardState.ACTIVE,
            GuardState.IDLE,
            GuardState.WARNING,
        }:
            return None

        _, _, policy = resolve_policy_for_simulation(presence.simulation)
        if policy.inactivity_pause_seconds <= 0:
            return None

        if not presence.last_presence_at:
            return None

        age = (now - presence.last_presence_at).total_seconds()
        guard = RuntimeGuard(presence, policy)

        # Check pause first (more severe).
        pause_decision = guard.should_pause(age)
        if not pause_decision.allowed:
            presence.guard_state = GuardState.PAUSED_INACTIVITY
            presence.pause_reason = PauseReason.INACTIVITY
            presence.paused_at = now
            presence.engine_runnable = False
            presence.save(
                update_fields=[
                    "guard_state",
                    "pause_reason",
                    "paused_at",
                    "engine_runnable",
                    "modified_at",
                ]
            )
            _emit_guard_event(
                simulation_id,
                "guard.state.updated",
                {
                    "guard_state": GuardState.PAUSED_INACTIVITY,
                    "pause_reason": PauseReason.INACTIVITY,
                },
            )
            logger.info(
                "guards.autopause.inactivity",
                simulation_id=simulation_id,
                age_seconds=int(age),
            )
            # Also pause the actual TrainerLab session so the tick loop stops
            # and active elapsed time is frozen.  Guard state was set first so
            # the re-entrant _sync_guard_pause call inside pause_session()
            # will see NON_RUNNABLE and short-circuit.
            _autopause_trainerlab_session(simulation_id)
            return GuardState.PAUSED_INACTIVITY

        # Check warning.
        warn_decision = guard.should_warn(age)
        if not warn_decision.allowed and presence.guard_state != GuardState.WARNING:
            presence.guard_state = GuardState.WARNING
            presence.warning_sent_at = now
            presence.save(update_fields=["guard_state", "warning_sent_at", "modified_at"])
            _emit_guard_event(
                simulation_id,
                "guard.warning.updated",
                {
                    "guard_state": GuardState.WARNING,
                    "seconds_until_pause": int(policy.inactivity_pause_seconds - age),
                },
            )
            logger.info(
                "guards.warning.inactivity",
                simulation_id=simulation_id,
                age_seconds=int(age),
            )
            return GuardState.WARNING

    return None


def _autopause_trainerlab_session(simulation_id: int) -> None:
    """Pause the TrainerLab session when guard inactivity fires.

    Guard state is already set to PAUSED_INACTIVITY before this is called.
    This stops the tick loop and freezes active elapsed time in TrainerLab.
    The re-entrant _sync_guard_pause() inside pause_session() is a no-op
    because it sees the presence already in NON_RUNNABLE_STATES.
    """
    try:
        from apps.trainerlab.models import SessionStatus, TrainerSession
        from apps.trainerlab.services import pause_session

        session = TrainerSession.objects.get(simulation_id=simulation_id)
        if session.status == SessionStatus.RUNNING:
            pause_session(session=session, user=None, correlation_id=None)
    except Exception:
        logger.exception(
            "guards.autopause.trainerlab_pause_failed",
            simulation_id=simulation_id,
        )


# ───────────────────────────────────────────────────────────────────────
# Runtime cap evaluation
# ───────────────────────────────────────────────────────────────────────


def evaluate_runtime_cap(
    simulation_id: int,
    active_elapsed: int,
) -> GuardState | None:
    """Check runtime cap and transition if exceeded.

    Returns the new state if a transition occurred.
    """
    with transaction.atomic():
        try:
            presence = SessionPresence.objects.select_for_update().get(
                simulation_id=simulation_id,
            )
        except SessionPresence.DoesNotExist:
            return None

        if presence.guard_state in NON_RUNNABLE_STATES:
            return None

        _, _, policy = resolve_policy_for_simulation(presence.simulation)
        guard = RuntimeGuard(presence, policy)
        decision = guard.check_runtime_cap(active_elapsed)

        if not decision.allowed:
            _transition_to_runtime_cap_paused(presence)
            return GuardState.PAUSED_RUNTIME_CAP

    return None


def _transition_to_runtime_cap_paused(presence: SessionPresence) -> None:
    """Transition a presence row to PAUSED_RUNTIME_CAP state."""
    now = timezone.now()
    presence.guard_state = GuardState.PAUSED_RUNTIME_CAP
    presence.pause_reason = PauseReason.RUNTIME_CAP
    presence.paused_at = now
    presence.runtime_locked_at = now
    presence.engine_runnable = False
    presence.save(
        update_fields=[
            "guard_state",
            "pause_reason",
            "paused_at",
            "runtime_locked_at",
            "engine_runnable",
            "modified_at",
        ]
    )
    _emit_guard_event(
        presence.simulation_id,
        "guard.state.updated",
        {
            "guard_state": GuardState.PAUSED_RUNTIME_CAP,
            "pause_reason": PauseReason.RUNTIME_CAP,
        },
    )
    logger.info(
        "guards.runtime_cap_reached",
        simulation_id=presence.simulation_id,
    )


# ───────────────────────────────────────────────────────────────────────
# Wall-clock expiry evaluation
# ───────────────────────────────────────────────────────────────────────


def evaluate_wall_clock(simulation_id: int) -> GuardState | None:
    """Check wall-clock expiry and transition if needed."""
    now = timezone.now()

    with transaction.atomic():
        try:
            presence = SessionPresence.objects.select_for_update().get(
                simulation_id=simulation_id,
            )
        except SessionPresence.DoesNotExist:
            return None

        if presence.guard_state in NON_RUNNABLE_STATES:
            return None

        if not presence.wall_clock_expires_at:
            return None

        if now >= presence.wall_clock_expires_at:
            presence.guard_state = GuardState.ENDED
            presence.pause_reason = PauseReason.WALL_CLOCK_EXPIRY
            presence.paused_at = now
            presence.engine_runnable = False
            presence.save(
                update_fields=[
                    "guard_state",
                    "pause_reason",
                    "paused_at",
                    "engine_runnable",
                    "modified_at",
                ]
            )
            _emit_guard_event(
                simulation_id,
                "guard.state.updated",
                {
                    "guard_state": GuardState.ENDED,
                    "pause_reason": PauseReason.WALL_CLOCK_EXPIRY,
                },
            )
            logger.info("guards.wall_clock_expired", simulation_id=simulation_id)
            return GuardState.ENDED

    return None


# ───────────────────────────────────────────────────────────────────────
# Resumption
# ───────────────────────────────────────────────────────────────────────


def resume_guard_state(simulation_id: int) -> GuardDecision:
    """Attempt to resume a paused session from the guard framework side.

    Only inactivity-paused sessions can be resumed.  Runtime-cap pauses
    are terminal for engine progression.
    """
    now = timezone.now()

    with transaction.atomic():
        presence = SessionPresence.objects.select_for_update().get(
            simulation_id=simulation_id,
        )
        _, _, policy = resolve_policy_for_simulation(presence.simulation)
        guard = RuntimeGuard(presence, policy)
        decision = guard.may_resume_session()
        if not decision.allowed:
            return decision

        presence.guard_state = GuardState.ACTIVE
        presence.pause_reason = PauseReason.NONE
        presence.paused_at = None
        presence.warning_sent_at = None
        presence.engine_runnable = True
        presence.last_presence_at = now
        presence.save(
            update_fields=[
                "guard_state",
                "pause_reason",
                "paused_at",
                "warning_sent_at",
                "engine_runnable",
                "last_presence_at",
                "modified_at",
            ]
        )

    _emit_guard_event(
        simulation_id,
        "guard.state.updated",
        {"guard_state": GuardState.ACTIVE, "pause_reason": PauseReason.NONE},
    )
    return GuardDecision.allow()


# ───────────────────────────────────────────────────────────────────────
# Pre-session budget check
# ───────────────────────────────────────────────────────────────────────


def check_pre_session_budget(
    user,
    account,
    lab_type: str,
    product_code: str,
) -> GuardDecision:
    """TrainerLab pre-session token budget admission check.

    Verifies that the user/account has enough remaining token budget
    for initial scenario generation + safety reserve.
    """
    policy = resolve_policy(lab_type, product_code)
    usage_snapshot = get_usage_snapshot(user_id=user.pk, account_id=account.pk)

    # Build a temporary presence for the decision layer.
    temp_presence = SessionPresence(
        lab_type=lab_type,
        guard_state=GuardState.ACTIVE,
        engine_runnable=True,
    )
    guard = RuntimeGuard(temp_presence, policy)
    return guard.may_start_session(usage_snapshot)


# ───────────────────────────────────────────────────────────────────────
# ChatLab send-lock check
# ───────────────────────────────────────────────────────────────────────


def check_chat_send_allowed(simulation_id: int) -> GuardDecision:
    """Check if ChatLab should allow sending a message.

    Returns a ``GuardDecision`` with denial reason if locked, or
    advisory warnings if nearing limits.
    """
    try:
        presence = SessionPresence.objects.select_related("simulation").get(
            simulation_id=simulation_id,
        )
    except SessionPresence.DoesNotExist:
        return GuardDecision.allow()

    _, _, policy = resolve_policy_for_simulation(presence.simulation)
    usage_snapshot = get_usage_snapshot(
        simulation_id=simulation_id,
        user_id=presence.simulation.user_id,
        account_id=presence.simulation.account_id,
    )
    guard = RuntimeGuard(presence, policy)
    return guard.should_lock_send(usage_snapshot)


# ───────────────────────────────────────────────────────────────────────
# Usage accounting
# ───────────────────────────────────────────────────────────────────────


def get_usage_snapshot(
    *,
    simulation_id: int | None = None,
    user_id: int | None = None,
    account_id: int | None = None,
) -> dict[str, int]:
    """Aggregate current usage from ``UsageRecord`` for the given scopes.

    Returns a dict like::

        {
            "session_total_tokens": 12345,
            "user_total_tokens": 67890,
            "account_total_tokens": 111213,
        }
    """
    result: dict[str, int] = {}

    if simulation_id is not None:
        agg = UsageRecord.objects.filter(
            scope_type=UsageScopeType.SESSION,
            simulation_id=simulation_id,
        ).aggregate(total=Sum("total_tokens"))
        result["session_total_tokens"] = agg["total"] or 0

    if user_id is not None:
        agg = UsageRecord.objects.filter(
            scope_type=UsageScopeType.USER,
            user_id=user_id,
        ).aggregate(total=Sum("total_tokens"))
        result["user_total_tokens"] = agg["total"] or 0

    if account_id is not None:
        agg = UsageRecord.objects.filter(
            scope_type=UsageScopeType.ACCOUNT,
            account_id=account_id,
        ).aggregate(total=Sum("total_tokens"))
        result["account_total_tokens"] = agg["total"] or 0

    return result


def record_usage(
    *,
    simulation_id: int,
    user_id: int | None,
    account_id: int | None,
    lab_type: str,
    product_code: str,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int = 0,
    total_tokens: int,
) -> None:
    """Increment usage counters at session / user / account level.

    Called after each completed ServiceCall (via the signal handler in
    ``apps.guards.signals``).
    """
    now = timezone.now()
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    _upsert_usage(
        scope_type=UsageScopeType.SESSION,
        simulation_id=simulation_id,
        user_id=None,
        account_id=None,
        lab_type=lab_type,
        product_code=product_code,
        period_start=period_start,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
    )

    if user_id is not None:
        _upsert_usage(
            scope_type=UsageScopeType.USER,
            simulation_id=None,
            user_id=user_id,
            account_id=None,
            lab_type=lab_type,
            product_code=product_code,
            period_start=period_start,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
        )

    if account_id is not None:
        _upsert_usage(
            scope_type=UsageScopeType.ACCOUNT,
            simulation_id=None,
            user_id=None,
            account_id=account_id,
            lab_type=lab_type,
            product_code=product_code,
            period_start=period_start,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
        )


def _upsert_usage(
    *,
    scope_type: str,
    simulation_id: int | None,
    user_id: int | None,
    account_id: int | None,
    lab_type: str,
    product_code: str,
    period_start,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    total_tokens: int,
) -> None:
    """Concurrency-safe upsert: create-or-increment a UsageRecord row.

    Uses select_for_update() to lock the row if it exists, then falls back
    to a create protected by the unique constraint.  If a concurrent insert
    wins the race, the IntegrityError is caught and we retry the update.
    """
    from django.db import IntegrityError

    lookup = {
        "scope_type": scope_type,
        "lab_type": lab_type,
        "product_code": product_code,
        "period_start": period_start,
    }
    if simulation_id is not None:
        lookup["simulation_id"] = simulation_id
    if user_id is not None:
        lookup["user_id"] = user_id
    if account_id is not None:
        lookup["account_id"] = account_id

    increments = {
        "input_tokens": F("input_tokens") + input_tokens,
        "output_tokens": F("output_tokens") + output_tokens,
        "reasoning_tokens": F("reasoning_tokens") + reasoning_tokens,
        "total_tokens": F("total_tokens") + total_tokens,
        "service_call_count": F("service_call_count") + 1,
    }

    with transaction.atomic():
        # Lock any existing row so concurrent updates serialize correctly.
        updated = UsageRecord.objects.filter(**lookup).select_for_update().update(**increments)
        if updated:
            return

        # No existing row — create one.  The unique constraint prevents
        # duplicate rows if two workers arrive here simultaneously.
        try:
            UsageRecord.objects.create(
                **lookup,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
                total_tokens=total_tokens,
                service_call_count=1,
            )
        except IntegrityError:
            # A concurrent worker won the race and created the row first.
            # Retry the update now that the row exists.
            UsageRecord.objects.filter(**lookup).update(**increments)


# ───────────────────────────────────────────────────────────────────────
# Guard state retrieval (for API / UI)
# ───────────────────────────────────────────────────────────────────────


def get_guard_state_for_simulation(
    simulation_id: int,
) -> dict[str, Any]:
    """Return the current guard state as a dict suitable for API responses.

    Returns structured warning and denial objects via the presentation
    layer rather than free-form strings.
    """
    from .presentation import (
        denial_for_state,
        warning_approaching_runtime_cap,
        warning_inactivity,
    )

    try:
        presence = SessionPresence.objects.select_related("simulation").get(
            simulation_id=simulation_id,
        )
    except SessionPresence.DoesNotExist:
        return {
            "guard_state": GuardState.ACTIVE,
            "guard_reason": PauseReason.NONE,
            "engine_runnable": True,
            "active_elapsed_seconds": 0,
            "runtime_cap_seconds": None,
            "wall_clock_expires_at": None,
            "warnings": [],
            "denial": None,
        }

    _, _, policy = resolve_policy_for_simulation(presence.simulation)

    # Compute active elapsed from TrainerLab session if applicable.
    active_elapsed = 0
    if presence.lab_type == LabType.TRAINERLAB:
        active_elapsed = _get_trainerlab_active_elapsed(presence.simulation)

    # Collect structured warnings.
    warnings: list[dict[str, Any]] = []
    if policy.has_runtime_cap and presence.guard_state == GuardState.ACTIVE:
        remaining = policy.runtime_cap_seconds - active_elapsed
        if 0 < remaining <= 300:
            warnings.append(warning_approaching_runtime_cap(remaining, policy.runtime_cap_seconds))

    if presence.guard_state == GuardState.WARNING:
        age = 0.0
        if presence.last_presence_at:
            age = (timezone.now() - presence.last_presence_at).total_seconds()
        seconds_until_pause = max(0, int(policy.inactivity_pause_seconds - age))
        warnings.append(warning_inactivity(seconds_until_pause))

    # Build structured denial for non-runnable states.
    denial = denial_for_state(presence.guard_state, presence.pause_reason)

    return {
        "guard_state": presence.guard_state,
        "guard_reason": presence.pause_reason,
        "engine_runnable": presence.engine_runnable,
        "active_elapsed_seconds": active_elapsed,
        "runtime_cap_seconds": policy.runtime_cap_seconds,
        "wall_clock_expires_at": (
            presence.wall_clock_expires_at.isoformat() if presence.wall_clock_expires_at else None
        ),
        "warnings": warnings,
        "denial": denial,
    }


def _get_trainerlab_active_elapsed(simulation) -> int:
    """Get active elapsed seconds from the TrainerLab session."""
    try:
        from apps.trainerlab.services import get_active_elapsed_seconds

        session = simulation.trainerlab_session
        return get_active_elapsed_seconds(session)
    except Exception:
        return 0


# ───────────────────────────────────────────────────────────────────────
# Outbox event helper
# ───────────────────────────────────────────────────────────────────────


def _emit_guard_event(
    simulation_id: int,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Emit a guard state-change event via the outbox."""
    try:
        from apps.common.outbox import enqueue_event_sync, poke_drain_sync

        event = enqueue_event_sync(
            event_type=event_type,
            simulation_id=simulation_id,
            payload=payload,
            idempotency_key=f"{event_type}:{simulation_id}:{payload.get('guard_state', '')}",
        )
        if event:
            poke_drain_sync()
    except Exception:
        logger.exception(
            "guards.emit_event_failed",
            simulation_id=simulation_id,
            event_type=event_type,
        )
