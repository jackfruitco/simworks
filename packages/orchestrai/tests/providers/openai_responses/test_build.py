import json

from orchestrai.components.services.providers.openai_responses.build import build_responses_request
from orchestrai.contrib.provider_backends.openai.tools import OpenAIToolAdapter
from orchestrai.types import Request
from orchestrai.types.content import ContentRole
from orchestrai.types.input import InputTextContent
from orchestrai.types.messages import InputItem
from orchestrai.types.tools import BaseLLMTool


def _make_message(role: ContentRole, text: str) -> InputItem:
    return InputItem(role=role, content=[InputTextContent(text=text)])


def test_build_responses_request_with_codec_and_tools() -> None:
    tool = BaseLLMTool(
        name="sum_numbers",
        description="Add two numbers",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
        strict=True,
    )
    provider_tool = OpenAIToolAdapter().to_provider(tool)

    req = Request(
        model="gpt-4.1-mini",
        input=[
            _make_message(ContentRole.SYSTEM, "Be helpful"),
            _make_message(ContentRole.USER, "Add numbers"),
        ],
        tools=[tool],
        provider_response_format={
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": {"type": "object", "properties": {}}},
        },
        max_output_tokens=256,
        previous_response_id="resp_123",
    )

    payload = build_responses_request(
        req=req,
        model="gpt-4.1-mini",
        provider_tools=[provider_tool],
        timeout=15,
    )

    assert payload["model"] == "gpt-4.1-mini"
    assert len(payload["input"]) == 2
    assert payload["tools"] == [provider_tool]
    assert payload["text"]["json_schema"]["name"] == "response"
    assert payload["metadata"]["orchestrai"].get("response_format") == "text"
    assert "sum_numbers" in payload["metadata"]["orchestrai"].get("tools_declared", [])

    # Must serialize cleanly for logging/inspection
    json.dumps(payload)


def test_build_responses_request_uses_schema_fallback_and_is_json_safe() -> None:
    schema = {"type": "object", "properties": {"result": {"type": "string"}}}
    req = Request(
        model=None,
        input=[_make_message(ContentRole.USER, "ping")],
        response_schema_json=schema,
        tools=[],
    )

    payload = build_responses_request(req=req, model="gpt-4.1", provider_tools=None)

    assert payload["text"] == schema
    # Metadata should include a hint that a response format is present
    assert payload.get("metadata", {}).get("orchestrai", {}).get("response_format") == "text"

    json.dumps(payload)
