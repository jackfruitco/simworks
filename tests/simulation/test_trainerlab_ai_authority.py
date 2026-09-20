"""AI proposals may only commit against the generation and state they observed."""

import pytest

from apps.accounts.models import UserRole
from apps.trainerlab.models import HeartRate, ProgressionPlan, RuntimeEvent
from apps.trainerlab.services import (
    _capture_ai_generation,
    _mark_runtime_service_call_active,
    append_pending_runtime_reason,
    apply_runtime_turn_output,
    apply_vitals_progression_output,
    clear_runtime_processing,
    create_session,
    fail_vitals_generation,
    get_runtime_state,
)


@pytest.fixture
def session(django_user_model):
    role = UserRole.objects.create(title="Authority test")
    user = django_user_model.objects.create_user(
        email="authority@example.com", password="test", role=role
    )
    session = create_session(user=user, scenario_spec={}, directives="", modifiers=[])
    session.status = "running"
    session.save(update_fields=["status"])
    return session


def claim(session, worker="runtime"):
    session.refresh_from_db()
    state = get_runtime_state(session)
    generation = _capture_ai_generation(session, state, worker)
    if worker == "runtime":
        state["runtime_processing"] = True
        state["currently_processing_reasons"] = [{"reason_kind": "manual_tick", "payload": {}}]
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json"])
    return {"ai_generation": generation, "call_id": generation["token"]}


def apply(session, context, worker="runtime"):
    vital = {"vital_type": "heart_rate", "min_value": 80, "max_value": 90}
    if worker == "runtime":
        return apply_runtime_turn_output(
            session_id=session.id,
            service_context=context,
            output_payload={"state_changes": {"vital_updates": [vital]}},
        )
    return apply_vitals_progression_output(
        session_id=session.id, service_context=context, output_payload={"vitals": [vital]}
    )


@pytest.mark.django_db
@pytest.mark.parametrize("worker", ["runtime", "vitals"])
def test_duplicate_completion_cannot_apply_twice(session, worker):
    HeartRate.objects.create(simulation=session.simulation, min_value=70, max_value=75)
    context = claim(session, worker)
    apply(session, context, worker)
    assert HeartRate.objects.filter(simulation=session.simulation).count() == 1
    assert ProgressionPlan.objects.filter(session=session).count() == (
        1 if worker == "runtime" else 0
    )
    apply(session, context, worker)
    assert HeartRate.objects.filter(simulation=session.simulation).count() == 1
    assert ProgressionPlan.objects.filter(session=session).count() == (
        1 if worker == "runtime" else 0
    )


@pytest.mark.django_db
@pytest.mark.parametrize("worker", ["runtime", "vitals"])
@pytest.mark.parametrize("change", ["revision", "input", "pause"])
def test_changed_state_rejects_ai_physiology(session, worker, change):
    context = claim(session, worker)
    if change == "input":
        append_pending_runtime_reason(
            session=session, reason_kind="intervention_recorded", payload={"domain_event_id": 123}
        )
    else:
        if change == "revision":
            session.runtime_state_json["state_revision"] += 1
        else:
            session.status = "paused"
        session.save(update_fields=["runtime_state_json", "status"])
    apply(session, context, worker)
    assert not HeartRate.objects.filter(simulation=session.simulation).exists()
    assert RuntimeEvent.objects.filter(
        session=session, payload__rejected__0__reason="state_changed_during_generation"
    ).exists()


@pytest.mark.django_db
def test_old_result_and_failure_cannot_clear_new_generation(session):
    old = claim(session)
    current = claim(session)
    apply(session, old)
    assert (
        clear_runtime_processing(session_id=session.id, expected_generation=old["ai_generation"])
        is False
    )
    session.refresh_from_db()
    assert session.runtime_state_json["runtime_generation"] == current["ai_generation"]
    assert session.runtime_state_json["runtime_processing"] is True


@pytest.mark.django_db
def test_vitals_failure_does_not_clear_runtime(session):
    runtime = claim(session)
    vitals = claim(session, "vitals")
    fail_vitals_generation(session_id=session.id, service_context=vitals)
    session.refresh_from_db()
    assert session.runtime_state_json["runtime_generation"] == runtime["ai_generation"]
    assert session.runtime_state_json["runtime_processing"] is True
    assert "vitals_generation" not in session.runtime_state_json


@pytest.mark.django_db
def test_unknown_intervention_rejects_entire_patch(session):
    context = claim(session)
    apply_runtime_turn_output(
        session_id=session.id,
        service_context=context,
        output_payload={
            "state_changes": {
                "vital_updates": [{"vital_type": "heart_rate", "min_value": 80, "max_value": 90}],
                "intervention_assessments": [
                    {"intervention_event_id": 999999, "effectiveness": "effective"}
                ],
            }
        },
    )
    assert not HeartRate.objects.filter(simulation=session.simulation).exists()
    assert RuntimeEvent.objects.filter(
        session=session, payload__rejected__0__reason="non_authoritative_intervention"
    ).exists()


@pytest.mark.django_db
def test_fast_completion_is_not_reactivated_by_enqueue_bookkeeping(session):
    context = claim(session)
    apply(session, context)
    _mark_runtime_service_call_active(
        session_id=session.id, call_id="late", generation=context["ai_generation"]
    )
    session.refresh_from_db()
    assert not session.runtime_state_json["runtime_processing"]
    assert not session.runtime_state_json["active_service_call_id"]


@pytest.mark.django_db
def test_unversioned_result_is_never_applied(session):
    claim(session)
    apply(session, {})
    assert not HeartRate.objects.filter(simulation=session.simulation).exists()
