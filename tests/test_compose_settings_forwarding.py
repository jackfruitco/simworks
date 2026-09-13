"""Guards that documented env vars actually reach the deployed containers.

`docker/compose.yaml` passes an explicit allowlist (`x-app-env`) rather than the
whole `.env` file, so a variable can be documented in `docker/.env.example` and
still be invisible to the server. VoiceLab surfaced this as a `503` on
`POST /api/v1/simulations/<id>/voice/session/` with no key in the container.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = REPO_ROOT / "docker" / "compose.yaml"
ENV_EXAMPLE_PATH = REPO_ROOT / "docker" / ".env.example"

# Variables the application reads at runtime that must survive the allowlist.
REQUIRED_APP_ENV_VARS = (
    "ORCA_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "VOICELAB_REALTIME_MODEL",
    "VOICELAB_REALTIME_VOICE",
    "VOICELAB_TRANSCRIPTION_MODEL",
    "VOICELAB_CONTEXT_MESSAGE_LIMIT",
    "VOICELAB_OPENAI_CLIENT_SECRETS_URL",
    "VOICELAB_OPENAI_CALLS_URL",
    "VOICELAB_OPENAI_WEBSOCKET_URL",
)

# Services that run application code and therefore need the full app env.
APP_SERVICES = ("server", "celery", "celerybeat")


def _load_compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text())


@pytest.mark.parametrize("var_name", REQUIRED_APP_ENV_VARS)
def test_app_env_anchor_forwards_required_var(var_name):
    app_env = _load_compose()["x-app-env"]
    assert var_name in app_env, (
        f"{var_name} is read by the application but is not forwarded in "
        "docker/compose.yaml x-app-env, so containers never see it."
    )
    assert app_env[var_name] == "${" + var_name + "}"


@pytest.mark.parametrize("service_name", APP_SERVICES)
@pytest.mark.parametrize("var_name", REQUIRED_APP_ENV_VARS)
def test_app_services_receive_required_var(service_name, var_name):
    compose = _load_compose()
    environment = compose["services"][service_name]["environment"]
    assert var_name in environment, f"{service_name} is missing {var_name}"


@pytest.mark.parametrize("var_name", REQUIRED_APP_ENV_VARS)
def test_env_example_documents_required_var(var_name):
    lines = ENV_EXAMPLE_PATH.read_text().splitlines()
    documented = {line.split("=", 1)[0].lstrip("# ").strip() for line in lines if "=" in line}
    assert var_name in documented, f"{var_name} is not documented in docker/.env.example"
