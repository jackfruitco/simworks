from datetime import UTC

from django.utils import timezone
import pytest

from apps.accounts.models import UserRole
from apps.common.models import OutboxEvent
from apps.trainerlab.models import SessionStatus, TrainerAgentViewModelRecord
from apps.trainerlab.orca.services.runtime import GenerateTrainerRuntimeTurn
from apps.trainerlab.services import (
    append_pending_runtime_reason,
    apply_runtime_turn_output,
    create_session,
    enqueue_runtime_turn_service_call,
    get_runtime_state,
    process_runtime_turn_queue,
    schedule_runtime_turn_once,
)
from orchestrai_django.models import CallStatus, ServiceCall
from orchestrai_django.signals import ai_response_failed


class _FakeEncoding:
    """Fake tiktoken encoding that avoids network downloads in tests."""

    def encode(self, text: str) -> list[int]:
        return list(range(max(1, len(text) // 4)))


def _create_running_session(django_user_model, *, email: str):
    role = UserRole.objects.create(title=f"TrainerLab Runtime Scheduling {email}")
    user = django_user_model.objects.create_user(
        email=email,
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
    return session


@pytest.fixture(autouse=True)
def _mock_tiktoken_encoding(monkeypatch):
    monkeypatch.setattr(
        "apps.trainerlab.runtime_llm._encoding_for_model",
        lambda model_name: _FakeEncoding(),
    )


@pytest.mark.django_db
def test_rapid_intervention_reasons_coalesce_one_scheduled_runtime_call(
    django_user_model,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    session = _create_running_session(
        django_user_model,
        email="runtime-coalesce@example.com",
    )
    scheduled: list[dict[str, object]] = []

    monkeypatch.setattr(
        "apps.trainerlab.services._enqueue_runtime_turn_task",
        lambda **kwargs: scheduled.append(kwargs),
    )

    with django_capture_on_commit_callbacks(execute=True):
        append_pending_runtime_reason(
            session=session,
            reason_kind="intervention_recorded",
            payload={"domain_event_id": 101, "event_kind": "intervention"},
        )
        append_pending_runtime_reason(
            session=session,
            reason_kind="intervention_recorded",
            payload={"domain_event_id": 102, "event_kind": "intervention"},
        )

    session.refresh_from_db()
    state = get_runtime_state(session)
    assert [r["payload"]["domain_event_id"] for r in state["pending_runtime_reasons"]] == [
        101,
        102,
    ]
    assert len(scheduled) == 1
    assert state["scheduled_runtime_task_run_at"]


@pytest.mark.django_db
def test_intervention_reason_during_active_runtime_call_does_not_enqueue_parallel(
    django_user_model,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    session = _create_running_session(
        django_user_model,
        email="runtime-active@example.com",
    )
    state = get_runtime_state(session)
    state["runtime_processing"] = True
    state["active_service_call_id"] = "call-active"
    state["currently_processing_reasons"] = [
        {"reason_kind": "manual_tick", "payload": {}, "created_at": "2026-03-22T00:00:00Z"}
    ]
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])

    scheduled: list[dict[str, object]] = []
    monkeypatch.setattr(
        "apps.trainerlab.services._enqueue_runtime_turn_task",
        lambda **kwargs: scheduled.append(kwargs),
    )

    with django_capture_on_commit_callbacks(execute=True):
        append_pending_runtime_reason(
            session=session,
            reason_kind="intervention_recorded",
            payload={"domain_event_id": 201, "event_kind": "intervention"},
        )

    session.refresh_from_db()
    state = get_runtime_state(session)
    assert scheduled == []
    assert state["pending_runtime_reasons"][-1]["payload"]["domain_event_id"] == 201
    assert state["active_service_call_id"] == "call-active"


@pytest.mark.django_db
def test_runtime_completion_schedules_one_follow_up_for_pending_reasons(
    django_user_model,
    monkeypatch,
):
    session = _create_running_session(
        django_user_model,
        email="runtime-follow-up@example.com",
    )
    state = get_runtime_state(session)
    state["runtime_processing"] = True
    state["active_service_call_id"] = "call-current"
    state["currently_processing_reasons"] = [
        {"reason_kind": "manual_tick", "payload": {}, "created_at": "2026-03-22T00:00:00Z"}
    ]
    state["pending_runtime_reasons"] = [
        {
            "reason_kind": "intervention_recorded",
            "payload": {"domain_event_id": 301, "event_kind": "intervention"},
            "created_at": "2026-03-22T00:00:01Z",
        }
    ]
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])

    scheduled: list[dict[str, object]] = []
    monkeypatch.setattr(
        "apps.trainerlab.services._enqueue_runtime_turn_task",
        lambda **kwargs: scheduled.append(kwargs),
    )

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
            "rationale_notes": [],
        },
        service_context={"correlation_id": "follow-up", "call_id": "call-current"},
    )

    session.refresh_from_db()
    state = get_runtime_state(session)
    assert len(scheduled) == 1
    assert state["active_service_call_id"] == ""
    assert state["currently_processing_reasons"] == []
    assert state["pending_runtime_reasons"][0]["payload"]["domain_event_id"] == 301
    assert state["chained_turn_count"] == 1


@pytest.mark.django_db
def test_run_start_schedules_runtime_immediately(django_user_model, monkeypatch):
    session = _create_running_session(
        django_user_model,
        email="runtime-run-start@example.com",
    )
    state = get_runtime_state(session)
    state["pending_runtime_reasons"] = [
        {"reason_kind": "run_started", "payload": {}, "created_at": "2026-03-22T00:00:00Z"}
    ]
    state["pending_since"] = "2026-03-22T00:00:00Z"
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])

    scheduled: list[dict[str, object]] = []
    monkeypatch.setattr(
        "apps.trainerlab.services._enqueue_runtime_turn_task",
        lambda **kwargs: scheduled.append(kwargs),
    )

    assert schedule_runtime_turn_once(session_id=session.id, trigger_kind="run/start") is True
    assert len(scheduled) == 1
    assert scheduled[0]["session_id"] == session.id


@pytest.mark.django_db
def test_run_tick_respects_runtime_min_interval(django_user_model, monkeypatch):
    session = _create_running_session(
        django_user_model,
        email="runtime-tick-min@example.com",
    )
    state = get_runtime_state(session)
    state["pending_runtime_reasons"] = [
        {"reason_kind": "tick", "payload": {}, "created_at": "2026-03-22T00:00:00Z"}
    ]
    state["pending_since"] = "2026-03-22T00:00:00Z"
    state["last_runtime_call_at"] = timezone.now().astimezone(UTC).isoformat()
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])

    scheduled: list[dict[str, object]] = []
    monkeypatch.setattr(
        "apps.trainerlab.services._enqueue_runtime_turn_task",
        lambda **kwargs: scheduled.append(kwargs),
    )

    assert schedule_runtime_turn_once(session_id=session.id, trigger_kind="run/tick") is False
    session.refresh_from_db()
    assert scheduled == []
    assert get_runtime_state(session)["scheduled_runtime_task_run_at"] is None


@pytest.mark.django_db
def test_max_chained_turns_prevents_follow_up_schedule(
    django_user_model,
    monkeypatch,
    settings,
):
    settings.TRAINERLAB_RUNTIME_MAX_CHAINED_TURNS = 2
    session = _create_running_session(
        django_user_model,
        email="runtime-max-chain@example.com",
    )
    state = get_runtime_state(session)
    state["pending_runtime_reasons"] = [
        {
            "reason_kind": "intervention_recorded",
            "payload": {"domain_event_id": 401, "event_kind": "intervention"},
            "created_at": "2026-03-22T00:00:00Z",
        }
    ]
    state["pending_since"] = "2026-03-22T00:00:00Z"
    state["chained_turn_count"] = 2
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])

    scheduled: list[dict[str, object]] = []
    monkeypatch.setattr(
        "apps.trainerlab.services._enqueue_runtime_turn_task",
        lambda **kwargs: scheduled.append(kwargs),
    )

    assert (
        schedule_runtime_turn_once(session_id=session.id, trigger_kind="runtime_follow_up") is False
    )
    assert scheduled == []


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
            "trainer_agent_view_model": {
                "simulation_id": 11,
                "session_id": 22,
                "status": "running",
                "scenario_snapshot": {"causes": [], "problems": []},
                "runtime_snapshot": {"state_revision": 3},
                "event_timeline": {"events": [], "total_events": 0},
                "trigger_reasons": [{"reason_kind": "tick", "count": 2}],
                "metadata": {
                    "builder_version": "v1",
                    "schema_version": "v1",
                    "snapshot_cache": {
                        "status": "disabled",
                        "authoritative": False,
                        "source": "disabled",
                    },
                },
            },
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
    assert "trainer_agent_view_model" in context
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
    assert "trainer_agent_view_model" in call.context
    assert "previous_response_id" not in call.context
    assert "previous_provider_response_id" not in call.context
    assert str(call.context["runtime_request_metrics"]["service_call_id"]).replace("-", "") == str(
        call.id
    ).replace("-", "")
    assert call.context["runtime_request_metrics"]["previous_response_id_present"] is False
    record = TrainerAgentViewModelRecord.objects.get(service_call=call)
    assert call.context["trainer_agent_view_model_record_id"] == record.id
    assert record.session_id == session.id
    assert record.correlation_id == ""
    assert record.builder_version == "v1"
    assert record.schema_version == "v1"
    assert record.payload_json["simulation_id"] == session.simulation_id
    assert record.payload_json["session_id"] == session.id
    assert record.payload_json["runtime_snapshot"]["state_revision"] >= 0
    assert record.payload_json["metadata"]["builder_version"] == "v1"
    assert record.payload_json["metadata"]["schema_version"] == "v1"


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
