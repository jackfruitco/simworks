from __future__ import annotations

from collections.abc import Iterable

from tests.conftest import FailureArtifactCollector


def assert_response_status(
    response: object,
    expected_status: int,
    *,
    failure_artifacts: FailureArtifactCollector | None = None,
) -> None:
    actual_status = getattr(response, "status_code", None)
    if failure_artifacts is not None:
        failure_artifacts.capture_response(response)
    assert actual_status == expected_status, (
        f"Unexpected status code. expected={expected_status} actual={actual_status}"
    )


def assert_payload_has_fields(
    payload: dict[str, object],
    fields: Iterable[str],
    *,
    failure_artifacts: FailureArtifactCollector | None = None,
) -> None:
    missing = [field for field in fields if field not in payload]
    if missing and failure_artifacts is not None:
        failure_artifacts.record("payload", payload)
        failure_artifacts.record("missing_fields", missing)
    assert not missing, f"Payload missing required fields: {missing}"
