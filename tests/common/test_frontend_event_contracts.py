"""Contract tests for frontend event wiring used by tool refresh."""

from pathlib import Path

from apps.common.outbox import event_types as outbox_events


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_event_bus_knows_assessment_created_event():
    source = _read("SimWorks/apps/common/static/common/js/simulation-event-bus.js")
    assert f"'{outbox_events.ASSESSMENT_CREATED}'" in source


def test_chat_tool_config_listens_for_assessment_created():
    source = _read("SimWorks/apps/chatlab/static/chatlab/js/chat.js")
    assert "'simulation_assessment'" in source
    assert f"'{outbox_events.ASSESSMENT_CREATED}'" in source


def test_new_message_button_is_nested_in_messages_panel_stack():
    source = _read("SimWorks/apps/chatlab/templates/chatlab/chat.html")
    panel_index = source.index('id="chat-messages-panel"')
    stack_index = source.index('id="chat-messages-stack"')
    messages_index = source.index('id="chat-messages"')
    button_index = source.index('id="new-message-btn"')
    assert panel_index < stack_index < messages_index < button_index


def test_unread_dedupe_tracks_seen_message_ids():
    source = _read("SimWorks/apps/chatlab/static/chatlab/js/chat.js")
    assert "seenMessageIds" in source
    assert "_hasSeenMessage" in source
    assert "_rememberSeenMessage" in source


def test_load_older_button_visibility_is_top_and_failure_bound():
    source = _read("SimWorks/apps/chatlab/templates/chatlab/chat.html")
    assert "isAtMessagesTop && hasMoreMessages && olderLoadFailed" in source


def test_trainerlab_event_contract_includes_friendly_labels():
    source = _read("SimWorks/apps/common/static/common/js/simulation-events.d.ts")
    assert "march_category_label?: string;" in source
    assert "anatomical_location_label?: string;" in source
    assert "laterality_label?: string;" in source
    assert "injury_location_label?: string;" in source
    assert "injury_kind_label?: string;" in source
    assert "intervention_label?: string;" in source
    assert "site_label?: string;" in source
    assert (
        f"'{outbox_events.PATIENT_INJURY_CREATED}' | '{outbox_events.PATIENT_INJURY_UPDATED}'"
        in source
    )
    assert (
        f"'{outbox_events.PATIENT_ILLNESS_CREATED}' | '{outbox_events.PATIENT_ILLNESS_UPDATED}'"
        in source
    )
    assert f"'{outbox_events.PATIENT_PROBLEM_CREATED}'" in source
    assert f"'{outbox_events.PATIENT_RECOMMENDED_INTERVENTION_CREATED}'" in source
    assert (
        f"'{outbox_events.PATIENT_INTERVENTION_CREATED}'"
        f" | '{outbox_events.PATIENT_INTERVENTION_UPDATED}'" in source
    )
    assert f"'{outbox_events.SIMULATION_SNAPSHOT_UPDATED}'" in source
    assert f"'{outbox_events.SIMULATION_PLAN_UPDATED}'" in source
    assert f"'{outbox_events.PATIENT_ASSESSMENT_FINDING_CREATED}'" in source
    assert f"'{outbox_events.PATIENT_DIAGNOSTIC_RESULT_CREATED}'" in source
    assert f"'{outbox_events.PATIENT_RESOURCE_UPDATED}'" in source
    assert f"'{outbox_events.PATIENT_DISPOSITION_UPDATED}'" in source
    assert (
        f"'{outbox_events.PATIENT_VITAL_CREATED}' | '{outbox_events.PATIENT_VITAL_UPDATED}'"
        in source
    )
    assert (
        f"'{outbox_events.PATIENT_PULSE_CREATED}' | '{outbox_events.PATIENT_PULSE_UPDATED}'"
        in source
    )
    assert "cause_kind: 'injury' | 'illness';" in source
    assert "recommended_interventions?: TrainerLabRecommendedInterventionFields[];" in source
    assert "active?: boolean;" in source
    assert "initiated_by_type: 'user' | 'instructor' | 'system';" in source
    assert "type: 'trainerlab.condition.created';" not in source
    assert "type: 'trainerlab.event.created';" not in source


def test_trainerlab_typescript_contract_covers_backend_event_surface():
    source = _read("SimWorks/apps/common/static/common/js/simulation-events.d.ts")
    backend_event_types = {
        outbox_events.SIMULATION_ADJUSTMENT_ACCEPTED,
        outbox_events.SIMULATION_PLAN_UPDATED,
        outbox_events.PATIENT_ILLNESS_CREATED,
        outbox_events.PATIENT_ILLNESS_UPDATED,
        outbox_events.PATIENT_INJURY_CREATED,
        outbox_events.PATIENT_INJURY_UPDATED,
        outbox_events.PATIENT_INTERVENTION_CREATED,
        outbox_events.PATIENT_INTERVENTION_UPDATED,
        outbox_events.SIMULATION_NOTE_CREATED,
        outbox_events.PATIENT_PROBLEM_CREATED,
        outbox_events.PATIENT_PROBLEM_UPDATED,
        outbox_events.PATIENT_RECOMMENDED_INTERVENTION_CREATED,
        outbox_events.PATIENT_RECOMMENDED_INTERVENTION_UPDATED,
        outbox_events.PATIENT_RECOMMENDED_INTERVENTION_REMOVED,
        outbox_events.SIMULATION_RUNTIME_FAILED,
        outbox_events.SIMULATION_STATUS_UPDATED,
        outbox_events.SIMULATION_SNAPSHOT_UPDATED,
        outbox_events.SIMULATION_SUMMARY_UPDATED,
        outbox_events.SIMULATION_ANNOTATION_CREATED,
        outbox_events.PATIENT_ASSESSMENT_FINDING_CREATED,
        outbox_events.PATIENT_ASSESSMENT_FINDING_UPDATED,
        outbox_events.PATIENT_ASSESSMENT_FINDING_REMOVED,
        outbox_events.PATIENT_DIAGNOSTIC_RESULT_CREATED,
        outbox_events.PATIENT_DIAGNOSTIC_RESULT_UPDATED,
        outbox_events.PATIENT_DISPOSITION_UPDATED,
        outbox_events.PATIENT_PULSE_CREATED,
        outbox_events.PATIENT_PULSE_UPDATED,
        outbox_events.PATIENT_RECOMMENDATION_EVALUATION_CREATED,
        outbox_events.PATIENT_RESOURCE_UPDATED,
        outbox_events.SIMULATION_BRIEF_CREATED,
        outbox_events.SIMULATION_BRIEF_UPDATED,
        outbox_events.SIMULATION_TICK_TRIGGERED,
        outbox_events.PATIENT_VITAL_CREATED,
        outbox_events.PATIENT_VITAL_UPDATED,
        outbox_events.SIMULATION_PRESET_APPLIED,
        outbox_events.SIMULATION_COMMAND_ACCEPTED,
    }
    for event_type in backend_event_types:
        assert f"'{event_type}'" in source
