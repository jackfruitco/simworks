from pathlib import Path

from orchestrai.components.services.service import BaseService, register_task_proxy_factory
from orchestrai.identity import Identity
from orchestrai.identity.domains import SERVICES_DOMAIN


class _BoundaryService(BaseService):
    abstract = False
    identity = Identity(domain=SERVICES_DOMAIN, namespace="tests", group="boundary", name="svc")

    async def arun(self, **ctx):
        return {"ctx": ctx}


def test_core_package_sources_do_not_reference_orchestrai_django():
    root = Path(__file__).resolve().parents[1] / "src" / "orchestrai"
    offenders: list[str] = []

    for path in root.rglob("*.py"):
        if "orchestrai_django" in path.read_text(encoding="utf-8"):
            offenders.append(str(path))

    assert offenders == []


def test_task_proxy_preserves_dispatch_metadata_without_framework_coupling():
    register_task_proxy_factory(None)
    proxy = _BoundaryService.task.using(backend="celery", queue="priority", task_id="abc")

    try:
        call = proxy.run(value=1)
        task_id = proxy.enqueue(value=2)

        assert call.status == "succeeded"
        assert call.dispatch["backend"] == "celery"
        assert call.dispatch["queue"] == "priority"
        assert call.dispatch["task_id"] == "abc"
        assert isinstance(task_id, str)
    finally:
        register_task_proxy_factory(None)
