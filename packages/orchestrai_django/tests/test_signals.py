import types

from orchestrai_django import signals


def test_emit_service_call_dispatched_sends_generic_payload(monkeypatch):
    captured = []

    def _capture(sender, **payload):
        captured.append((sender, payload))
        return []

    monkeypatch.setattr(signals.service_call_dispatched, "send_robust", _capture)

    call = types.SimpleNamespace(
        id="call-1",
        service_identity="services.test.native.output",
        context={
            "simulation_id": 123,
            "correlation_id": "corr-1",
            "user_msg": 456,
        },
    )

    signals.emit_service_call_dispatched(call, attempt=2)

    assert len(captured) == 1
    sender, payload = captured[0]
    assert sender is type(call)
    assert payload["call"] is call
    assert payload["call_id"] == "call-1"
    assert payload["attempt"] == 2
    assert payload["service_identity"] == "services.test.native.output"
    assert payload["simulation_id"] == 123
    assert payload["correlation_id"] == "corr-1"
    assert payload["context"]["user_msg"] == 456
