"""Regression tests for TrainerLab active-elapsed accounting.

These guard against the double-counting bug where _finalize_runtime_views()
wrote get_active_elapsed_seconds() into active_elapsed_seconds without
advancing the anchor, causing every subsequent finalize call to re-add the
full span from the original anchor.
"""

from __future__ import annotations

from datetime import UTC, timedelta

from django.utils import timezone
import pytest

from apps.accounts.models import UserRole
from apps.trainerlab.models import SessionStatus
from apps.trainerlab.services import (
    _checkpoint_active_elapsed,
    _finalize_runtime_views,
    build_runtime_state_defaults,
    create_session,
    get_active_elapsed_seconds,
    get_runtime_state,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def user(db, django_user_model):
    role = UserRole.objects.create(title="Elapsed Accounting Test Role")
    return django_user_model.objects.create_user(
        email="elapsed-test@example.com",
        password="pass12345",
        role=role,
    )


@pytest.fixture
def running_session(user):
    session = create_session(user=user, scenario_spec={}, directives="", modifiers=[])
    session.status = SessionStatus.RUNNING
    session.save(update_fields=["status", "modified_at"])
    return session


class TestCheckpointActiveElapsed:
    def test_running_session_folds_and_advances_anchor(self, running_session):
        now = timezone.now()
        anchor = now - timedelta(seconds=100)
        state = build_runtime_state_defaults(state={
            "active_elapsed_seconds": 0,
            "active_elapsed_anchor_started_at": anchor.astimezone(UTC).isoformat(),
        })

        result = _checkpoint_active_elapsed(running_session, state=state, now=now)

        assert result["active_elapsed_seconds"] == 100
        # Anchor must advance to now, not remain at the original anchor.
        new_anchor = result["active_elapsed_anchor_started_at"]
        assert new_anchor is not None
        assert new_anchor == now.astimezone(UTC).isoformat()

    def test_repeated_checkpoints_are_monotonic(self, running_session):
        t0 = timezone.now()
        anchor = t0 - timedelta(seconds=50)
        state = build_runtime_state_defaults(state={
            "active_elapsed_seconds": 0,
            "active_elapsed_anchor_started_at": anchor.astimezone(UTC).isoformat(),
        })

        # First checkpoint at t0: folds 50 s, anchor → t0
        state = _checkpoint_active_elapsed(running_session, state=state, now=t0)
        assert state["active_elapsed_seconds"] == 50

        # Second checkpoint 30 s later: should add only 30 s, not re-add the 50 s
        t1 = t0 + timedelta(seconds=30)
        state = _checkpoint_active_elapsed(running_session, state=state, now=t1)
        assert state["active_elapsed_seconds"] == 80

    def test_paused_session_does_not_fold_anchor(self, running_session):
        running_session.status = SessionStatus.PAUSED
        running_session.save(update_fields=["status", "modified_at"])

        now = timezone.now()
        anchor = (now - timedelta(seconds=60)).astimezone(UTC).isoformat()
        state = build_runtime_state_defaults(state={
            "active_elapsed_seconds": 200,
            "active_elapsed_anchor_started_at": anchor,
        })

        result = _checkpoint_active_elapsed(running_session, state=state, now=now)

        # Stored value unchanged; anchor delta NOT added for non-RUNNING session.
        assert result["active_elapsed_seconds"] == 200

    def test_no_anchor_does_not_crash(self, running_session):
        state = build_runtime_state_defaults(state={
            "active_elapsed_seconds": 300,
            "active_elapsed_anchor_started_at": None,
        })

        result = _checkpoint_active_elapsed(running_session, state=state)

        assert result["active_elapsed_seconds"] == 300


class TestFinalizeRuntimeViewsDoesNotDoubleCounting:
    def test_multiple_finalizes_give_monotonic_elapsed(self, running_session):
        t0 = timezone.now()
        anchor = t0 - timedelta(seconds=60)

        state = get_runtime_state(running_session)
        state["active_elapsed_seconds"] = 0
        state["active_elapsed_anchor_started_at"] = anchor.astimezone(UTC).isoformat()
        running_session.runtime_state_json = state
        running_session.save(update_fields=["runtime_state_json", "modified_at"])

        # First finalize at t0: elapsed should be ~60 s
        _finalize_runtime_views(session=running_session, state=state, now=t0)

        running_session.refresh_from_db()
        elapsed_after_first = running_session.runtime_state_json["active_elapsed_seconds"]
        assert elapsed_after_first == 60

        # Second finalize 30 s later: elapsed should be ~90 s (60 + 30), not 150 or more
        t1 = t0 + timedelta(seconds=30)
        state2 = running_session.runtime_state_json
        _finalize_runtime_views(session=running_session, state=state2, now=t1)

        running_session.refresh_from_db()
        elapsed_after_second = running_session.runtime_state_json["active_elapsed_seconds"]
        assert elapsed_after_second == 90

    def test_get_active_elapsed_seconds_matches_checkpoint_after_finalize(self, running_session):
        """Verify that get_active_elapsed_seconds() stays coherent after finalize."""
        t0 = timezone.now()
        anchor = t0 - timedelta(seconds=45)

        state = get_runtime_state(running_session)
        state["active_elapsed_seconds"] = 0
        state["active_elapsed_anchor_started_at"] = anchor.astimezone(UTC).isoformat()
        running_session.runtime_state_json = state
        running_session.save(update_fields=["runtime_state_json", "modified_at"])

        _finalize_runtime_views(session=running_session, state=state, now=t0)
        running_session.refresh_from_db()

        # Immediately after finalize, the live view should match the stored value.
        live_elapsed = get_active_elapsed_seconds(
            running_session,
            state=running_session.runtime_state_json,
            now=t0,
        )
        assert live_elapsed == 45
