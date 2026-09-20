"""Voice capture is audit metadata, never autonomous intervention authority."""

from pydantic import ValidationError
import pytest

from api.v1.schemas.trainerlab import InterventionCreateIn


def voice_payload(**overrides):
    payload = {
        "intervention_type": "tourniquet",
        "site_code": "left_arm",
        "target_problem_id": 1,
        "details": {"kind": "tourniquet", "version": 1, "application_mode": "hasty"},
        "client_event_id": "capture-123",
        "voice_provenance": {
            "capture_id": "capture-123",
            "original_transcript": "No tourniquet applied",
            "reviewed_transcript": "Tourniquet applied",
            "confirmed": True,
        },
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("confirmed", [False, None, "true"])
def test_unconfirmed_voice_action_rejected(confirmed):
    payload = voice_payload()
    payload["voice_provenance"]["confirmed"] = confirmed
    with pytest.raises(ValidationError):
        InterventionCreateIn.model_validate(payload)


@pytest.mark.parametrize("field", ["original_transcript", "reviewed_transcript", "capture_id"])
def test_blank_voice_audit_fields_rejected(field):
    payload = voice_payload()
    payload["voice_provenance"][field] = " "
    with pytest.raises(ValidationError):
        InterventionCreateIn.model_validate(payload)


def test_capture_identity_required_for_duplicate_protection():
    with pytest.raises(ValidationError):
        InterventionCreateIn.model_validate(voice_payload(client_event_id="another-capture"))


def test_transcript_is_audit_only_and_does_not_set_action_details():
    body = InterventionCreateIn.model_validate(voice_payload())
    assert body.voice_provenance.original_transcript == "No tourniquet applied"
    assert body.effectiveness == "unknown"
    assert body.notes == ""
    assert body.intervention_type == "tourniquet"


def test_existing_manual_clients_remain_compatible():
    body = InterventionCreateIn.model_validate(voice_payload(voice_provenance=None))
    assert body.voice_provenance is None
