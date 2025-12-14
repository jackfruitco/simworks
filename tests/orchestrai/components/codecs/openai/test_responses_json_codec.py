# tests/orchestrai/components/codecs/openai/test_responses_json_codec.py

import pytest
from pydantic import BaseModel

from orchestrai.components.codecs.exceptions import CodecDecodeError, CodecSchemaError
from orchestrai.contrib.provider_codecs.openai import OpenAIResponsesJsonCodec
from orchestrai.types import Request, Response
from orchestrai.types.content import ContentRole
from orchestrai.types.messages import OutputItem
from orchestrai.types.output import OutputTextContent


class SimpleSchema(BaseModel):
    foo: str


def _make_request_with_schema(schema_cls: type[BaseModel]) -> Request:
    return Request(
        model=None,
        input=[],
        response_schema=schema_cls,
    )


def _make_response_with_structured_payload(
    payload: dict,
    schema_cls: type[BaseModel] | None = None,
) -> Response:
    req = Request(model=None, input=[])
    if schema_cls is not None:
        req.response_schema = schema_cls  # type: ignore[assignment]

    return Response(
        request=req,
        provider_meta={"structured": payload},
    )


def test_encode_with_pydantic_schema_builds_openai_payload():
    codec = OpenAIResponsesJsonCodec()
    req = _make_request_with_schema(SimpleSchema)

    codec.encode(req)

    # response_schema_json should be a dict JSON Schema
    assert isinstance(req.response_schema_json, dict)
    inner_schema = req.response_schema_json.get("json_schema", {}).get("schema", {})
    assert "properties" in inner_schema
    assert "foo" in inner_schema.get("properties", {})

    # provider_response_format should be the OpenAI JSON envelope
    provider_format = getattr(req, "provider_response_format", None)
    assert isinstance(provider_format, dict)
    assert provider_format.get("type") in ("json_schema", "object")

    json_schema = provider_format.get("json_schema") or {}
    assert json_schema.get("name") == "response"
    assert isinstance(json_schema.get("schema"), dict)


def test_encode_with_raw_schema_dict_and_flatten_unions_applied():
    codec = OpenAIResponsesJsonCodec()
    raw_schema = {
        "oneOf": [
            {"type": "object", "properties": {"a": {"type": "string"}}},
            {"type": "object", "properties": {"b": {"type": "string"}}},
        ]
    }
    req = Request(model=None, input=[], response_schema_json=raw_schema)

    codec.encode(req)

    # The flattened schema should not contain oneOf and should merge properties.
    assert isinstance(req.response_schema_json, dict)
    compiled = req.response_schema_json
    assert "oneOf" not in compiled.get("json_schema", {}).get("schema", {})
    assert compiled.get("type") == "json_schema"
    props = compiled.get("json_schema", {}).get("schema", {}).get("properties") or {}
    assert "a" in props and "b" in props

    provider_format = getattr(req, "provider_response_format", None)
    assert isinstance(provider_format, dict)
    assert provider_format.get("type") == "json_schema"


def test_encode_no_schema_is_noop():
    codec = OpenAIResponsesJsonCodec()
    req = Request(model=None, input=[])

    codec.encode(req)

    # No schema provided -> codec should not attach a backend payload.
    assert req.response_schema_json is None
    assert getattr(req, "provider_response_format", None) is None


def test_decode_with_schema_returns_pydantic_instance():
    codec = OpenAIResponsesJsonCodec()
    payload = {"foo": "bar"}
    resp = _make_response_with_structured_payload(payload, SimpleSchema)

    result = codec.decode(resp)

    assert isinstance(result, SimpleSchema)
    assert result.foo == "bar"


def test_decode_without_schema_returns_raw_dict():
    codec = OpenAIResponsesJsonCodec()
    payload = {"foo": "bar"}
    resp = _make_response_with_structured_payload(payload, schema_cls=None)

    result = codec.decode(resp)

    assert isinstance(result, dict)
    assert result == payload


def test_decode_with_invalid_payload_raises_codecdecodeerror():
    class IntSchema(BaseModel):
        foo: int

    codec = OpenAIResponsesJsonCodec()
    # Invalid type: foo should be int
    payload = {"foo": "not_an_int"}
    resp = _make_response_with_structured_payload(payload, IntSchema)

    with pytest.raises(CodecDecodeError):
        codec.decode(resp)


def test_decode_prefers_provider_structured_over_text_json():
    codec = OpenAIResponsesJsonCodec()
    payload = {"foo": "from_structured"}

    # Build a Response that has both provider_meta.structured and a JSON text output.
    req = Request(model=None, input=[])
    req.response_schema = SimpleSchema  # type: ignore[assignment]

    text_msg = OutputItem(
        role=ContentRole.ASSISTANT,
        content=[OutputTextContent(text='{"foo": "from_text"}')],
    )
    resp = Response(
        request=req,
        output=[text_msg],
        provider_meta={"structured": payload},
    )

    result = codec.decode(resp)

    # Provider-native structured payload should win over JSON text.
    assert isinstance(result, SimpleSchema)
    assert result.foo == "from_structured"


def test_encode_raises_on_non_dict_response_schema_json():
    codec = OpenAIResponsesJsonCodec()
    # Intentionally invalid: response_schema_json must be a dict
    req = Request(model=None, input=[], response_schema_json="not_a_dict")  # type: ignore[arg-type]

    with pytest.raises(CodecSchemaError):
        codec.encode(req)