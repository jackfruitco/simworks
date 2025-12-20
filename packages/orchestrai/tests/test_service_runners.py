import pytest

from orchestrai import OrchestrAI
from orchestrai.components.services.service import BaseService


class DummyService(BaseService):
    abstract = False

    async def arun(self, **ctx):
        return ctx or {"ok": True}


def test_local_runner_registered_and_used():
    app = OrchestrAI().set_as_current()

    with app.as_current():
        app.start()

        assert app.default_service_runner == "local"
        assert "local" in app.service_runners

        result = DummyService().task.enqueue()
        assert result == {"ok": True}


def test_missing_runner_raises():
    app = OrchestrAI().set_as_current()

    with app.as_current():
        app.start()
        call = DummyService().task.with_runner("bogus")

        with pytest.raises(LookupError):
            call.enqueue()
