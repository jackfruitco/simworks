import pytest

from orchestrai import OrchestrAI as CoreOrchestrAI
from orchestrai.shared import shared_service


@shared_service()
def shared_hello_service():
    return "hello"


def test_finalize_callbacks_run_for_multiple_apps():
    app_one = CoreOrchestrAI()
    app_one.finalize()

    assert "shared_hello_service" in app_one.services

    app_two = CoreOrchestrAI()
    app_two.finalize()

    assert "shared_hello_service" in app_two.services


def test_default_client_set_from_client_setting():
    app = CoreOrchestrAI()
    app.conf.update_from_mapping(
        {
            "CLIENT": "default-client",
            "CLIENTS": {
                "default-client": {"name": "default-client"},
            },
        }
    )

    app.setup()

    assert app.client == app.clients.get("default-client")


def test_default_client_uses_config_definition_over_placeholder():
    app = CoreOrchestrAI()
    app.conf.update_from_mapping(
        {
            "CLIENT": "configured-client",
            "CLIENTS": {"configured-client": {"name": "configured-client", "url": "http://example"}},
        }
    )

    app.setup()

    assert app.clients.get("configured-client")["url"] == "http://example"


def test_apps_entrypoint_aliases_core_orchestrai():
    with pytest.warns(DeprecationWarning, match="orchestrai.apps" ):
        from orchestrai.apps import OrchestrAI as AppsOrchestrAI

    assert AppsOrchestrAI is CoreOrchestrAI


def test_apps_entrypoint_warning_includes_example():
    from orchestrai.app import warn_deprecated_apps_import

    warn_deprecated_apps_import._already_warned = False  # type: ignore[attr-defined]

    with pytest.warns(DeprecationWarning) as recorded:
        warn_deprecated_apps_import(stacklevel=1)

    message = str(recorded.list[0].message)
    assert "Example: from orchestrai import OrchestrAI" in message


def test_start_prints_orca_banner_once(capsys):
    app = CoreOrchestrAI()

    app.start()
    first = capsys.readouterr().out

    # second call should not duplicate banner
    app.start()
    second = capsys.readouterr().out

    assert "ORCHESTRAI" in first
    assert "orca" in first.lower()
    assert first.count("ORCHESTRAI") == 1
    assert second.strip() == ""


def test_finalize_outputs_registered_components(capsys):
    app = CoreOrchestrAI()
    app.services.register("reporting", object())
    app.codecs.register("json", object())

    app.finalize()

    output = capsys.readouterr().out
    assert "Registered components:" in output
    assert "services: reporting" in output
    assert "codecs: json" in output
