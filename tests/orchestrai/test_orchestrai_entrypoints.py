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


def test_apps_entrypoint_aliases_core_orchestrai():
    with pytest.warns(DeprecationWarning):
        from orchestrai.apps import OrchestrAI as AppsOrchestrAI

    assert AppsOrchestrAI is CoreOrchestrAI
