import pytest

from orchestrai.client.factory import build_orca_client
from orchestrai.client.registry import clear_clients, list_clients
from orchestrai.client.settings_loader import OrcaSettings


@pytest.fixture(autouse=True)
def _reset_clients():
    clear_clients()
    yield
    clear_clients()


def test_single_client_builds_without_providers():
    core = OrcaSettings.from_mapping(
        {
            "MODE": "single",
            "CLIENT": {
                "name": "solo",
                "provider": "openai",
                "surface": "responses",
                "api_key_envvar": "OPENAI_API_KEY",
                "model": "gpt-4o-mini",
            },
        }
    )

    client = build_orca_client(core, "solo")

    assert "solo" in list_clients()
    assert client is list_clients()["solo"]
    assert getattr(client.provider, "identity", None) is not None


def test_single_client_uses_model_defaults_when_behavior_missing():
    core = OrcaSettings.from_mapping(
        {
            "MODE": "single",
            "CLIENT": {
                "provider": "openai",
                "surface": "responses",
                "api_key_envvar": "OPENAI_API_KEY",
            },
        }
    )

    client = build_orca_client(core, "default")

    assert client.config.max_retries == 3
    assert client.config.telemetry_enabled is True
    assert client.config.log_prompts is False


def test_multi_mode_without_providers_hints_single_mode():
    core = OrcaSettings.from_mapping(
        {
            "MODE": "multi",
            "PROVIDERS": {},
            "CLIENTS": {},
        }
    )

    with pytest.raises(ValueError) as excinfo:
        build_orca_client(core, "default")

    assert "ORCA_CONFIG['CLIENT']" in str(excinfo.value)
