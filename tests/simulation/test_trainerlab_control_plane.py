import pytest

from apps.accounts.models import UserRole
from apps.trainerlab.models import SessionStatus
from apps.trainerlab.orca.schemas.runtime import RuntimeProblemObservation
from apps.trainerlab.services import (
    apply_runtime_turn_output,
    create_session,
    get_runtime_state,
)


@pytest.mark.django_db
def test_control_plane_execution_plan_progresses(django_user_model):
    role = UserRole.objects.create(title="TrainerLab CP Test Role")
    user = django_user_model.objects.create_user(
        email="cp-test@example.com",
        password="pass12345",
        role=role,
    )
    session = create_session(
        user=user,
        scenario_spec={},
        directives="",
        modifiers=[],
    )
    session.status = SessionStatus.RUNNING
    session.save(update_fields=["status", "modified_at"])

    state = get_runtime_state(session)
    state["currently_processing_reasons"] = [
        {"reason_kind": "tick", "payload": {}, "created_at": "2026-03-18T00:00:00Z"}
    ]
    state["runtime_processing"] = True
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])

    apply_runtime_turn_output(
        session_id=session.id,
        output_payload={
            "state_changes": {
                "problem_observations": [],
                "vital_updates": [],
                "pulse_updates": [],
                "finding_updates": [],
                "recommendation_suggestions": [],
                "intervention_assessments": [],
            },
            "patient_status": {"narrative": "stable"},
            "instructor_intent": {"summary": "observe"},
            "rationale_notes": ["ok"],
        },
        service_context={"correlation_id": "cp-test", "call_id": "call-1"},
    )

    session.refresh_from_db()
    debug = session.runtime_state_json.get("control_plane_debug") or {}
    assert debug.get("execution_plan") == ["core_runtime", "vitals", "recommendation", "narrative"]
    assert debug.get("current_step_index") == 3
    assert isinstance(debug.get("last_patch_evaluation"), dict)


@pytest.mark.django_db
def test_runtime_patch_provenance_fields_supported():
    proposal = RuntimeProblemObservation.model_validate(
        {
            "worker_kind": "core_runtime",
            "domains": ["problems"],
            "driver_reason_kinds": ["tick"],
            "driver_intervention_ids": [123],
            "source_call_id": "call-abc",
            "correlation_id": "corr-abc",
            "observation": "new_problem",
            "cause_kind": "injury",
            "cause_id": 7,
            "problem_kind": "hemorrhage",
            "title": "Hemorrhage",
        }
    )
    assert proposal.worker_kind == "core_runtime"
    assert proposal.source_call_id == "call-abc"
