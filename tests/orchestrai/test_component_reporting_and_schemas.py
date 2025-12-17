import logging

import pytest

from orchestrai import OrchestrAI
from orchestrai.components.codecs.codec import BaseCodec
from orchestrai.components.providerkit import BaseProvider
from orchestrai.components.promptkit import PromptSection
from orchestrai.components.schemas import BaseOutputSchema
from orchestrai.components.services.service import BaseService
from orchestrai.decorators import codec, provider_backend, prompt_section, schema, service
from orchestrai.registry.singletons import (
    codecs as codec_registry,
    prompt_sections as prompt_section_registry,
    provider_backends as provider_backends_registry,
    providers as providers_registry,
    schemas as schema_registry,
    services as service_registry,
)


@pytest.fixture(autouse=True)
def clear_component_registries():
    registries = (
        service_registry,
        codec_registry,
        schema_registry,
        prompt_section_registry,
        provider_backends_registry,
        providers_registry,
    )
    for registry in registries:
        registry._store.clear()
    yield
    for registry in registries:
        registry._store.clear()


def test_decorator_logs_use_category_labels(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO)

    @service(namespace="log", group="demo", name="svc")
    class LoggedService(BaseService):
        abstract = False

        def execute(self):
            return None

    assert any("[SERVICES]" in record.message for record in caplog.records)


def test_component_report_lists_discovered_components():
    @service(namespace="report", group="svc", name="demo")
    class ReportService(BaseService):
        abstract = False

        def execute(self):
            return None

    @codec(namespace="report", group="api", name="json")
    class ReportCodec(BaseCodec):
        abstract = False

    @schema(namespace="report", group="svc", name="schema")
    class ReportSchema(BaseOutputSchema):
        value: str

    @prompt_section(namespace="report", group="prompt", name="section")
    class ReportPrompt(PromptSection):
        abstract = False
        instruction = "demo"

    @provider_backend(namespace="report", group="api", name="backend")
    class ReportBackend(BaseProvider):
        abstract = False

    app = OrchestrAI("reporter")
    app.ensure_ready()
    report = app.component_report_text()

    assert "services.report.svc.demo" in report
    assert "codecs.report.api.json" in report
    assert "schemas.report.svc.schema" in report
    assert "prompt-sections.report.prompt.section" in report
    assert "provider-backends.report.api.backend" in report


@pytest.mark.asyncio
async def test_response_schema_resolves_and_attaches_request():
    @schema(namespace="chatlab", group="standardized_patient", name="initial")
    class PatientInitialSchema(BaseOutputSchema):
        value: str

    @service(namespace="chatlab", group="standardized_patient", name="initial")
    class PatientInitialService(BaseService):
        abstract = False
        provider_name = "openai.responses"

        def execute(self):
            return None

    svc = PatientInitialService()
    assert svc.response_schema is PatientInitialSchema

    req, codec_instance, attrs = await svc.aprepare(stream=False)

    assert req.response_schema is PatientInitialSchema
    assert isinstance(req.response_schema_json, dict)
    assert req.provider_response_format is not None
    assert codec_instance is None
