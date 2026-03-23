import pytest

from apps.accounts.models import UserRole
from apps.common.models import OutboxEvent
from apps.trainerlab.models import SessionStatus
from apps.trainerlab.orca.services.runtime import GenerateTrainerRuntimeTurn
from apps.trainerlab.services import (
    apply_runtime_turn_output,
    create_session,
    enqueue_runtime_turn_service_call,
    get_runtime_state,
    process_runtime_turn_queue,
)
from orchestrai_django.models import CallStatus, ServiceCall
from orchestrai_django.signals import ai_response_failed


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
def test_runtime_patch_provenance_is_backend_injected(django_user_model):
    role = UserRole.objects.create(title="TrainerLab Provenance Role")
    user = django_user_model.objects.create_user(
        email="provenance@example.com",
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
    state = get_runtime_state(session)
    state["currently_processing_reasons"] = [
        {
            "reason_kind": "intervention_recorded",
            "payload": {"event_kind": "intervention", "domain_event_id": 123},
            "created_at": "2026-03-22T00:00:00Z",
        },
        {
            "reason_kind": "tick",
            "payload": {},
            "created_at": "2026-03-22T00:00:05Z",
        },
    ]
    state["runtime_processing"] = True
    session.runtime_state_json = state
    session.save(update_fields=["status", "runtime_state_json", "modified_at"])

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
        service_context={"correlation_id": "corr-abc", "call_id": "call-abc"},
    )

    session.refresh_from_db()
    patch_summary = session.runtime_state_json["control_plane_debug"]["last_patch_evaluation"]
    assert patch_summary["worker_kind"] == "core_runtime"
    assert patch_summary["source_call_id"] == "call-abc"
    assert patch_summary["correlation_id"] == "corr-abc"
    assert patch_summary["driver_reason_kinds"] == ["intervention_recorded", "tick"]
    assert patch_summary["driver_intervention_ids"] == [123]


@pytest.mark.django_db
def test_runtime_enqueue_context_uses_compact_state_and_no_previous_response(monkeypatch):
    captured: dict[str, object] = {}

    class FakeTaskProxy:
        def using(self, **kwargs):
            captured["context"] = kwargs["context"]
            return self

        def enqueue(self, **kwargs):
            captured["payload"] = kwargs
            return "call-123"

    monkeypatch.setattr(GenerateTrainerRuntimeTurn, "task", FakeTaskProxy())
    call_id = enqueue_runtime_turn_service_call(
        {
            "simulation_id": 11,
            "session_id": 22,
            "runtime_reasons": [{"reason_kind": "tick", "count": 2}],
            "runtime_llm_context": {"active_elapsed_seconds": 30, "active_problems": []},
            "runtime_request_metrics": {"estimated_prompt_tokens": 123},
            "active_elapsed_seconds": 30,
            "correlation_id": "corr-123",
        }
    )

    assert call_id == "call-123"
    context = captured["context"]
    assert "current_snapshot" not in context
    assert "runtime_llm_context" in context
    assert "previous_response_id" not in context
    assert "previous_provider_response_id" not in context
    assert context["model_settings"]["max_tokens"] > 0
    assert "PreviousResponseMixin" not in {
        cls.__name__ for cls in GenerateTrainerRuntimeTurn.__mro__
    }


@pytest.mark.django_db
def test_runtime_service_call_persists_compact_context_and_request_profile(
    django_user_model,
    monkeypatch,
):
    role = UserRole.objects.create(title="TrainerLab Persisted Runtime Role")
    user = django_user_model.objects.create_user(
        email="persisted-runtime@example.com",
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
    state = get_runtime_state(session)
    state["pending_runtime_reasons"] = [
        {
            "reason_kind": "manual_tick",
            "payload": {"triggered_at": "2026-03-22T00:00:00Z"},
            "created_at": "2026-03-22T00:00:00Z",
        }
    ]
    session.runtime_state_json = state
    session.save(update_fields=["status", "runtime_state_json", "modified_at"])

    monkeypatch.setattr(
        "orchestrai_django.task_proxy.DjangoTaskProxy._dispatch_immediate",
        lambda self, call_id: f"task-{call_id}",
    )

    call_id = process_runtime_turn_queue(session_id=session.id)

    call = ServiceCall.objects.get(pk=call_id)
    assert "runtime_llm_context" in call.context
    assert "runtime_request_metrics" in call.context
    assert "current_snapshot" not in call.context
    assert "previous_response_id" not in call.context
    assert "previous_provider_response_id" not in call.context
    assert str(call.context["runtime_request_metrics"]["service_call_id"]).replace("-", "") == str(
        call.id
    ).replace("-", "")
    assert call.context["runtime_request_metrics"]["previous_response_id_present"] is False


@pytest.mark.django_db
def test_runtime_budget_block_restores_batch_and_records_profile(
    django_user_model,
    settings,
):
    settings.TRAINERLAB_RUNTIME_MAX_PROMPT_TOKENS = 10
    role = UserRole.objects.create(title="TrainerLab Budget Role")
    user = django_user_model.objects.create_user(
        email="budget@example.com",
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
    state["pending_runtime_reasons"] = [
        {
            "reason_kind": "steer_prompt",
            "payload": {"command_id": "cmd-1", "prompt": "very long prompt " * 200},
            "created_at": "2026-03-22T00:00:00Z",
        }
    ]
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])

    call_id = process_runtime_turn_queue(session_id=session.id)

    assert call_id is None
    session.refresh_from_db()
    debug = session.runtime_state_json["control_plane_debug"]
    assert debug["last_request_profile"]["budget_action"] == "blocked"
    assert debug["last_request_profile"]["prompt_budget_exceeded"] is True
    assert session.runtime_state_json["runtime_processing"] is False
    assert session.runtime_state_json["currently_processing_reasons"] == []
    assert session.runtime_state_json["pending_runtime_reasons"]
    assert "exceeded" in session.runtime_state_json["last_runtime_error"]
    assert ServiceCall.objects.count() == 0


@pytest.mark.django_db
def test_terminal_runtime_failure_requeues_processing_batch(django_user_model):
    role = UserRole.objects.create(title="TrainerLab Runtime Failure Role")
    user = django_user_model.objects.create_user(
        email="runtime-failure@example.com",
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
    state = get_runtime_state(session)
    state["currently_processing_reasons"] = [
        {"reason_kind": "tick", "payload": {}, "created_at": "2026-03-22T00:00:00Z"}
    ]
    state["runtime_processing"] = True
    session.runtime_state_json = state
    session.save(update_fields=["status", "runtime_state_json", "modified_at"])

    call = ServiceCall.objects.create(
        service_identity="services.trainerlab.default.trainer-runtime-turn",
        service_kwargs={},
        backend="immediate",
        status=CallStatus.FAILED,
        input={},
        context={
            "simulation_id": session.simulation_id,
            "session_id": session.id,
            "correlation_id": "corr-runtime-failed",
        },
        dispatch={},
    )

    ai_response_failed.send(
        sender=GenerateTrainerRuntimeTurn,
        call_id=call.id,
        error="rate limited",
        context=call.context,
        reason_code="provider_rate_limited",
        user_retryable=True,
    )

    session.refresh_from_db()
    assert session.runtime_state_json["runtime_processing"] is False
    assert session.runtime_state_json["currently_processing_reasons"] == []
    assert session.runtime_state_json["pending_runtime_reasons"][0]["reason_kind"] == "tick"
    assert session.runtime_state_json["last_runtime_error"] == "rate limited"
    assert OutboxEvent.objects.filter(
        simulation_id=session.simulation_id,
        event_type="simulation.runtime.failed",
    ).exists()
