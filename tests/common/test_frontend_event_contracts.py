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
    assert "details: InterventionDetails;" in source
    assert "type: 'trainerlab.event.created';" in source
    assert "type: 'trainerlab.condition.created';" in source
    assert "march_category: string;" in source
    assert "injury_location?: string;" in source
    assert "injury_kind?: string;" in source
    assert "intervention_code?: string;" not in source
    assert "legacy_code?: string;" not in source
    assert "type: 'injury.created';" not in source
    assert "type: 'intervention.created';" not in source
