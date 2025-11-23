# tests/types/test_dtos_response.py

from uuid import UUID

from pydantic import BaseModel

from simcore_ai.types.transport import (
    Request,
    Response,
    ResponseSchemaType,
)
from simcore_ai.types.content import TextContent
from simcore_ai.types import ContentRole, InputItem, UsageContent


class DummySchema(BaseModel):
    foo: str


def test_response_schema_type_alias_is_pydantic_model_type():
    # Type-level check: ResponseSchemaType should accept a Pydantic model class
    schema: ResponseSchemaType = DummySchema  # type: ignore[assignment]
    assert schema is DummySchema


def test_response_defaults_and_structure():
    # Minimal Response
    resp = Response()

    # identity defaults
    assert resp.namespace is None
    assert resp.kind is None
    assert resp.name is None

    # correlation defaults
    assert isinstance(resp.correlation_id, UUID)
    assert resp.request_correlation_id is None
    assert resp.request is None

    # provider / client
    assert resp.provider_name is None
    assert resp.client_name is None
    assert resp.received_at is None

    # payload defaults
    assert resp.output == []
    assert resp.usage is None
    assert resp.tool_calls == []
    assert resp.provider_meta == {}


def test_response_with_request_and_output():
    item = InputItem(role=ContentRole.USER, content=[TextContent(text="hi")])
    req = Request(model="gpt-4.1", input=[item])

    resp = Response(
        namespace="chatlab",
        kind="standardized_patient",
        name="initial",
        request_correlation_id=req.correlation_id,
        request=req,
        output=[],
        usage=UsageContent(input_tokens=10, output_tokens=20, total_tokens=30),
    )

    assert resp.namespace == "chatlab"
    assert resp.kind == "standardized_patient"
    assert resp.name == "initial"
    assert resp.request_correlation_id == req.correlation_id
    assert resp.request is req
    assert resp.usage.input_tokens == 10
    assert resp.usage.output_tokens == 20
    assert resp.usage.total_tokens == 30
