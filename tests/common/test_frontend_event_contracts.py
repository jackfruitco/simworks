"""Contract tests for frontend event wiring used by tool refresh."""

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_event_bus_knows_feedback_created_event():
    source = _read("SimWorks/apps/common/static/common/js/simulation-event-bus.js")
    assert "'feedback.created'" in source


def test_chat_tool_config_listens_for_feedback_created():
    source = _read("SimWorks/apps/chatlab/static/chatlab/js/chat.js")
    assert "'simulation_feedback'" in source
    assert "'feedback.created'" in source


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
    assert "injury_location_label?: string;" in source
    assert "injury_kind_label?: string;" in source
    assert "intervention_label?: string;" in source
    assert "site_label?: string;" in source
    assert "'injury.created' | 'injury.updated'" in source
    assert "'illness.created' | 'illness.updated'" in source
    assert "'problem.created'" in source
    assert "'recommended_intervention.created'" in source
    assert "'intervention.created' | 'intervention.updated'" in source
    assert "'state.updated'" in source
    assert "'ai.intent.updated'" in source
    assert "'trainerlab.assessment_finding.created'" in source
    assert "'trainerlab.diagnostic_result.created'" in source
    assert "'trainerlab.resource.updated'" in source
    assert "'trainerlab.disposition.updated'" in source
    assert "'trainerlab.vital.created' | 'trainerlab.vital.updated'" in source
    assert "'trainerlab.pulse.created' | 'trainerlab.pulse.updated'" in source
    assert "cause_kind: 'injury' | 'illness';" in source
    assert "recommended_interventions?: TrainerLabRecommendedInterventionFields[];" in source
    assert "active?: boolean;" in source
    assert "initiated_by_type: 'user' | 'instructor' | 'system';" in source
    assert "type: 'trainerlab.condition.created';" not in source
    assert "type: 'trainerlab.event.created';" not in source


def test_trainerlab_typescript_contract_covers_backend_event_surface():
    source = _read("SimWorks/apps/common/static/common/js/simulation-events.d.ts")
    backend_event_types = {
        "adjustment.accepted",
        "adjustment.applied",
        "ai.intent.updated",
        "illness.created",
        "illness.updated",
        "injury.created",
        "injury.updated",
        "intervention.created",
        "intervention.updated",
        "note.created",
        "problem.created",
        "problem.updated",
        "problem.resolved",
        "recommended_intervention.created",
        "recommended_intervention.updated",
        "recommended_intervention.removed",
        "run.paused",
        "run.resumed",
        "run.started",
        "run.stopped",
        "runtime.failed",
        "session.failed",
        "session.seeding",
        "session.seeded",
        "state.updated",
        "summary.ready",
        "summary.updated",
        "trainerlab.annotation.created",
        "trainerlab.assessment_finding.created",
        "trainerlab.assessment_finding.updated",
        "trainerlab.assessment_finding.removed",
        "trainerlab.diagnostic_result.created",
        "trainerlab.diagnostic_result.updated",
        "trainerlab.disposition.updated",
        "trainerlab.intervention.assessed",
        "trainerlab.pulse.created",
        "trainerlab.pulse.updated",
        "trainerlab.recommendation_evaluation.created",
        "trainerlab.resource.updated",
        "trainerlab.scenario_brief.created",
        "trainerlab.scenario_brief.updated",
        "trainerlab.tick.triggered",
        "trainerlab.vital.created",
        "trainerlab.vital.updated",
    }
    for event_type in backend_event_types:
        assert f"'{event_type}'" in source
