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


def test_emit_domain_object_created_sends_generic_payload(monkeypatch):
    captured = []

    def _capture(sender, **payload):
        captured.append((sender, payload))
        return []

    monkeypatch.setattr(signals.domain_object_created, "send_robust", _capture)

    call = types.SimpleNamespace(
        id="call-2",
        service_identity="services.test.native.output",
        context={"simulation_id": 321, "_service_call_attempt_id": "attempt-9"},
    )
    domain_obj = {"kind": "message"}

    signals.emit_domain_object_created(call, domain_obj=domain_obj)

    assert len(captured) == 1
    sender, payload = captured[0]
    assert sender is type(call)
    assert payload["call"] is call
    assert payload["call_id"] == "call-2"
    assert payload["service_identity"] == "services.test.native.output"
    assert payload["domain_obj"] == domain_obj
    assert payload["context"]["_service_call_attempt_id"] == "attempt-9"
