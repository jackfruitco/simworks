"""Finite-horizon progression, branch authority, and instructor control."""

from unittest.mock import patch

from django.core.exceptions import ValidationError
import pytest

from apps.accounts.models import UserRole
from apps.trainerlab.models import HeartRate, Illness, Problem, ProgressionPlan, ScenarioDecision
from apps.trainerlab.progression import (
    advance_progression,
    install_plan,
    propose_branch,
    resolve_decision,
)
from apps.trainerlab.services import (
    append_pending_runtime_reason,
    create_session,
    get_runtime_state,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def session(django_user_model):
    role = UserRole.objects.create(title="Progression instructor")
    user = django_user_model.objects.create_user(
        email="progression@example.com", password="test", role=role
    )
    session = create_session(user=user, scenario_spec={}, directives="", modifiers=[])
    session.status = "running"
    session.save(update_fields=["status"])
    HeartRate.objects.create(simulation=session.simulation, min_value=80, max_value=90)
    return session


def plan(session, duration=30):
    state = get_runtime_state(session)
    result = install_plan(
        session=session,
        state=state,
        targets=[{"vital_type": "heart_rate", "min_value": 100, "max_value": 110}],
        duration=duration,
        portrayal={"behavior": "Restless", "speech": "I feel dizzy"},
        source_call_id="test-call",
    )
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json"])
    return result


def advance(session, elapsed):
    with patch("apps.trainerlab.services.get_active_elapsed_seconds", return_value=elapsed):
        advance_progression(session_id=session.pk, tick_nonce=session.tick_nonce)


def test_interpolation_expiry_and_no_extrapolation(session):
    installed = plan(session)
    advance(session, 15)
    current = HeartRate.objects.get(simulation=session.simulation, is_active=True)
    assert (current.min_value, current.max_value) == (90, 100)
    advance(session, 80)
    current = HeartRate.objects.get(simulation=session.simulation, is_active=True)
    assert (current.min_value, current.max_value) == (100, 110)
    installed.refresh_from_db()
    assert installed.status == "expired"
    count = HeartRate.objects.count()
    advance(session, 900)
    assert HeartRate.objects.count() == count


def test_pause_stale_tick_and_instructor_hold(session):
    plan(session)
    current = HeartRate.objects.get(simulation=session.simulation, is_active=True)
    current.lock_value = True
    current.save(update_fields=["lock_value"])
    advance(session, 15)
    assert HeartRate.objects.count() == 1
    session.status = "paused"
    session.save(update_fields=["status"])
    advance(session, 20)
    assert HeartRate.objects.count() == 1
    advance_progression(session_id=session.pk, tick_nonce=session.tick_nonce + 1)
    assert HeartRate.objects.count() == 1


def test_authoritative_input_invalidates_plan(session):
    installed = plan(session)
    append_pending_runtime_reason(
        session=session, reason_kind="intervention_recorded", payload={"domain_event_id": 99}
    )
    installed.refresh_from_db()
    assert installed.status == "invalidated"
    advance(session, 15)
    assert HeartRate.objects.count() == 1


def test_invalid_plan_preserves_previous_plan(session):
    previous = plan(session)
    with pytest.raises(ValidationError):
        plan(session, duration=0)
    previous.refresh_from_db()
    assert previous.status == "active"
    assert ProgressionPlan.objects.count() == 1


def branch(session):
    cause = Illness.objects.create(simulation=session.simulation, name="Respiratory illness")
    return propose_branch(
        session=session,
        state=get_runtime_state(session),
        source_call_id="test-call",
        observation={
            "observation": "new_problem",
            "cause_kind": "illness",
            "cause_id": cause.id,
            "problem_kind": "hypoxia",
            "title": "Hypoxia",
            "description": "Hypoxia develops",
        },
    )


def test_branch_requires_authorization_and_replay_is_safe(session):
    decision = branch(session)
    assert not Problem.objects.exists()
    resolve_decision(
        session_id=session.pk, decision_id=decision.pk, approved=True, user=session.simulation.user
    )
    assert Problem.objects.count() == 1
    resolve_decision(
        session_id=session.pk, decision_id=decision.pk, approved=True, user=session.simulation.user
    )
    assert Problem.objects.count() == 1
    decision.refresh_from_db()
    assert decision.status == "approved"
    assert decision.decided_by_id == session.simulation.user_id


def test_rejected_or_stale_branch_never_changes_patient(session):
    decision = branch(session)
    resolve_decision(
        session_id=session.pk, decision_id=decision.pk, approved=False, user=session.simulation.user
    )
    assert not Problem.objects.exists()
    with pytest.raises(ValidationError):
        resolve_decision(
            session_id=session.pk,
            decision_id=decision.pk,
            approved=True,
            user=session.simulation.user,
        )
    session.refresh_from_db()
    decision = branch(session)
    append_pending_runtime_reason(session=session, reason_kind="steer_prompt", payload={})
    with pytest.raises(ValidationError):
        resolve_decision(
            session_id=session.pk,
            decision_id=decision.pk,
            approved=True,
            user=session.simulation.user,
        )
    assert ScenarioDecision.objects.get(pk=decision.pk).status == "stale"
    assert not Problem.objects.exists()


@pytest.mark.parametrize("authorized", [False, True])
def test_catalog_requires_scenario_authorization(session, authorized):
    from apps.trainerlab.services import _apply_progression_catalogs

    cause = Illness.objects.create(simulation=session.simulation, name="Airway obstruction")
    Problem.objects.create(
        simulation=session.simulation,
        cause_illness=cause,
        problem_kind="illness",
        kind="airway_obstruction",
        march_category="A",
        title="Obstruction",
        onset_elapsed_seconds=0,
    )
    if authorized:
        session.scenario_spec_json = {
            "authorized_progression_rules": ["progression.airway_obstruction_to_hypoxia"]
        }
    with patch("apps.trainerlab.services.get_active_elapsed_seconds", return_value=60):
        _apply_progression_catalogs(session=session, correlation_id=None)
    assert Problem.objects.filter(kind="hypoxia").exists() is authorized


def test_respiratory_illness_does_not_automatically_become_tension_pneumothorax(session):
    from apps.trainerlab.services import _apply_progression_catalogs

    cause = Illness.objects.create(simulation=session.simulation, name="Respiratory illness")
    Problem.objects.create(
        simulation=session.simulation,
        cause_illness=cause,
        problem_kind="illness",
        kind="respiratory_distress",
        march_category="R",
        title="Dyspnea",
        onset_elapsed_seconds=0,
    )
    with patch("apps.trainerlab.services.get_active_elapsed_seconds", return_value=900):
        _apply_progression_catalogs(session=session, correlation_id=None)
    assert not Problem.objects.filter(kind="tension_pneumothorax").exists()
