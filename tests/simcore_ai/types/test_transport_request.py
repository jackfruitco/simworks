# tests/types/test_dtos_request.py

from uuid import UUID

from pydantic import BaseModel

from simcore_ai.types.transport import (
    Request,
)
from simcore_ai.types.content import TextContent
from simcore_ai.types import ContentRole, InputContent, InputItem


class DummySchema(BaseModel):
    foo: str


def test_request_basic_defaults_and_correlation():
    item = InputItem(
        role=ContentRole.USER,
        content=[InputContent.__args__[0](text="hi")],  # TextContent via alias
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
    item = InputItem(role=ContentRole.USER, content=[TextContent(text="hi")])
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
