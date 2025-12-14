# tests/types/test_dtos_request.py

from uuid import UUID

from pydantic import BaseModel

from orchestrai.types.transport import Request
from orchestrai.types.content import ContentRole
from orchestrai.types.input import InputContent, InputTextContent
from orchestrai.types.messages import InputItem


class DummySchema(BaseModel):
    foo: str


def test_request_basic_defaults_and_correlation():
    item = InputItem(
        role=ContentRole.USER,
        content=[InputTextContent(text="hi")],
    )
    req = Request(model="gpt-4.1", input=[item])

    assert req.model == "gpt-4.1"
    assert req.input[0].role == ContentRole.USER
    assert isinstance(req.correlation_id, UUID)

    # identity defaults
    assert req.namespace is None
    assert req.kind is None
    assert req.name is None

    # schema/response format defaults
    assert req.response_schema is None
    assert req.response_schema_json is None
    assert req.provider_response_format is None

    # tools defaults
    assert req.tools == []
    assert req.tool_choice == "auto"

    # misc defaults
    assert req.previous_response_id is None
    assert req.temperature == 0.2
    assert req.max_output_tokens is None
    assert req.stream is False
    assert req.image_format is None


def test_request_with_response_schema_fields_populated():
    item = InputItem(role=ContentRole.USER, content=[InputTextContent(text="hi")])
    req = Request(
        model="gpt-4.1",
        input=[item],
        response_schema=DummySchema,
        response_schema_json={"type": "object", "properties": {"foo": {"type": "string"}}},
        provider_response_format={"type": "json_schema"},
    )

    assert req.response_schema is DummySchema
    assert req.response_schema_json["type"] == "object"
    assert req.provider_response_format["type"] == "json_schema"
