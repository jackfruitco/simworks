"""Instructor holds and clinical onset are measured on the simulation clock."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone
from ninja.errors import HttpError
import pytest

from api.v1.endpoints.trainerlab import _create_vital
from api.v1.schemas.trainerlab import VitalCreateIn
from apps.accounts.models import UserRole
from apps.trainerlab.models import (
    EventSource,
    HeartRate,
    Illness,
    PatientStatusState,
    Problem,
    SessionStatus,
)
from apps.trainerlab.services import (
    _apply_vital_change,
    _claim_runtime_turn_batch,
    _problem_age_seconds,
    append_pending_runtime_reason,
    create_session,
    override_patient_avpu,
    schedule_runtime_turn_once,
    trigger_manual_tick,
    update_problem_status,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def session(django_user_model):
    role = UserRole.objects.create(title="Phase III instructor")
    user = django_user_model.objects.create_user(
        email="phase3@example.com", password="testpass123", role=role
    )
    session = create_session(user=user, scenario_spec={}, directives="", modifiers=[])
    session.status = SessionStatus.PAUSED
    session.run_started_at = timezone.now() - timedelta(minutes=10)
    session.runtime_state_json = {
        "active_elapsed_seconds": 80,
        "active_elapsed_anchor_started_at": None,
    }
    session.save()
    return session


def test_paused_time_and_supersession_do_not_reset_problem_onset(session):
    cause = Illness.objects.create(
        simulation=session.simulation, source=EventSource.SYSTEM, name="Shock"
    )
    problem = Problem.objects.create(
        simulation=session.simulation,
        source=EventSource.SYSTEM,
        cause_illness=cause,
        problem_kind=Problem.ProblemKind.ILLNESS,
        kind="hypoperfusion_shock",
        code="hypoperfusion_shock",
        title="Shock",
        march_category=Problem.MARCHCategory.C,
        severity=Problem.Severity.HIGH,
        onset_elapsed_seconds=20,
    )
    assert _problem_age_seconds(session, problem) == 60
    updated = update_problem_status(session=session, problem_id=problem.pk, is_treated=True)
    assert updated.onset_elapsed_seconds == 20
    assert _problem_age_seconds(session, updated) == 60
    session.runtime_state_json["active_elapsed_seconds"] = 95
    session.save(update_fields=["runtime_state_json"])
    assert _problem_age_seconds(session, updated) == 75


def test_ai_cannot_replace_held_vital_until_instructor_releases_it(session):
    held = HeartRate.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        min_value=80,
        max_value=80,
        lock_value=True,
    )
    change = {"vital_type": "heart_rate", "min_value": 110, "max_value": 120}
    _apply_vital_change(session=session, change=change, correlation_id=None)
    held.refresh_from_db()
    assert held.is_active
    assert HeartRate.objects.filter(simulation=session.simulation).count() == 1

    held.lock_value = False
    held.save(update_fields=["lock_value"])
    _apply_vital_change(session=session, change=change, correlation_id=None)
    held.refresh_from_db()
    assert not held.is_active
    assert HeartRate.objects.get(simulation=session.simulation, is_active=True).min_value == 110


def test_instructor_vital_override_supersedes_current_and_rejects_stale_release(session):
    initial = HeartRate.objects.create(
        simulation=session.simulation,
        source=EventSource.SYSTEM,
        min_value=90,
        max_value=100,
    )
    held = _create_vital(
        session,
        VitalCreateIn(
            vital_type="heart_rate",
            min_value=80,
            max_value=80,
            lock_value=True,
        ),
    )
    initial.refresh_from_db()
    assert not initial.is_active
    assert held.supersedes_id == initial.id

    _create_vital(
        session,
        VitalCreateIn(
            vital_type="heart_rate",
            min_value=80,
            max_value=80,
            lock_value=False,
            supersedes_event_id=held.id,
        ),
    )
    with pytest.raises(HttpError) as exc:
        _create_vital(
            session,
            VitalCreateIn(
                vital_type="heart_rate",
                min_value=80,
                max_value=80,
                supersedes_event_id=held.id,
            ),
        )
    assert exc.value.status_code == 409


def test_pause_defers_ai_work_and_manual_advancement(session):
    append_pending_runtime_reason(
        session=session, reason_kind="intervention_recorded", payload={"domain_event_id": 7}
    )
    assert not schedule_runtime_turn_once(session_id=session.id, trigger_kind="user/intervention")
    assert _claim_runtime_turn_batch(session.id) is None
    session.refresh_from_db()
    assert len(session.runtime_state_json["pending_runtime_reasons"]) == 1
    with pytest.raises(ValidationError, match="Resume the session"):
        trigger_manual_tick(session=session)


def test_avpu_override_is_immediately_authoritative_and_auditable(session):
    previous = PatientStatusState.objects.create(
        simulation=session.simulation, source=EventSource.SYSTEM, avpu="alert"
    )
    initial_revision = int(session.runtime_state_json.get("state_revision", 0))
    updated = override_patient_avpu(session=session, avpu="pain")
    previous.refresh_from_db()
    session.refresh_from_db()

    assert not previous.is_active
    assert updated.source == EventSource.INSTRUCTOR
    assert updated.supersedes_id == previous.id
    assert updated.avpu == "pain"
    assert session.runtime_state_json["state_revision"] == initial_revision + 1
