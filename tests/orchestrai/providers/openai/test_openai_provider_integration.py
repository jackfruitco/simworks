# tests/orchestrai/providers/openai/test_openai_provider_integration.py

import asyncio

import pytest

from orchestrai.contrib.provider_backends.openai import OpenAIResponsesProvider
from orchestrai.types import Request, Response
from orchestrai.types.content import ContentRole
from orchestrai.types.messages import OutputItem
from orchestrai.types.output import OutputTextContent
from orchestrai.types.tools import BaseLLMTool


class FakeUsage:
    def __init__(self, input_tokens: int = 10, output_tokens: int = 5, total_tokens: int = 15) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        self.input_tokens_details = None
        self.output_tokens_details = None


class FakeOpenAIResponse:
    """Minimal stand-in for openai.types.responses.Response used by OpenAIResponsesProvider."""

    def __init__(self, text: str = "hello from openai") -> None:
        self.output_text = text
        self.output = []
        self.usage = FakeUsage()
        self.model = "gpt-4o-mini"
        self.id = "resp_test_123"

    def model_dump(self) -> dict:
        return {
            "id": self.id,
            "model": self.model,
            "output_text": self.output_text,
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "total_tokens": self.usage.total_tokens,
            },
        }


def test_call_uses_provider_response_format_for_text_and_adapts_response(monkeypatch):
    captured: dict = {}

    async def fake_create(*args, **kwargs):
        nonlocal captured
        captured = kwargs
        return FakeOpenAIResponse(text="structured reply")

    provider = OpenAIResponsesProvider(
        alias="openai:test",
        api_key="test-key",
        base_url="https://example.invalid",
        default_model="gpt-4o-mini",
        timeout_s=5,
    )

    # Patch the underlying OpenAI client
    monkeypatch.setattr(provider._client.responses, "create", fake_create)

    # Build a Request with tools and a provider_response_format already set by a codec.
    tool = BaseLLMTool(
        name="image_generation",
        description="Generate an image",
        input_schema={},
    )
    req = Request(
        model=None,
        input=[],
        tools=[tool],
    )
    req.provider_response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "schema": {"type": "object", "properties": {"foo": {"type": "string"}}},
            "strict": True,
        },
    }

    resp = asyncio.run(provider.call(req))

    # Ensure the backend called the OpenAI client with `text` derived from provider_response_format
    assert "text" in captured
    assert captured["text"] == req.provider_response_format

    # Tools should be adapted into backend-native tools (we only check presence here)
    assert "tools" in captured
    assert captured["tools"] is not None

    # The returned object should be the normalized Response DTO
    assert isinstance(resp, Response)
    assert resp.output  # at least one OutputItem from adapt_response
    first_msg = resp.output[0]
    assert isinstance(first_msg, OutputItem)
    assert first_msg.role == ContentRole.ASSISTANT
    assert first_msg.content
    assert isinstance(first_msg.content[0], OutputTextContent)
    assert first_msg.content[0].text == "structured reply"

    # Usage should be propagated from the backend response
    assert resp.usage is not None
    assert resp.usage.total_tokens == 15


def test_call_falls_back_to_response_schema_json_when_no_provider_response_format(monkeypatch):
    captured: dict = {}

    async def fake_create(*args, **kwargs):
        nonlocal captured
        captured = kwargs
        return FakeOpenAIResponse(text="fallback reply")

    provider = OpenAIResponsesProvider(
        alias="openai:test",
        api_key="test-key",
        base_url="https://example.invalid",
        default_model="gpt-4o-mini",
        timeout_s=5,
    )

    monkeypatch.setattr(provider._client.responses, "create", fake_create)

    raw_schema = {"type": "object", "properties": {"bar": {"type": "string"}}}
    req = Request(
        model=None,
        input=[],
        response_schema_json=raw_schema,
    )

    resp = asyncio.run(provider.call(req))

    # When provider_response_format is not set, the backend should fall back to response_schema_json
    assert "text" in captured
    assert captured["text"] == raw_schema

    # The response should still be adapted into a Response DTO
    assert isinstance(resp, Response)
    assert resp.output
    first_msg = resp.output[0]
    assert isinstance(first_msg, OutputItem)
    assert first_msg.content[0].text == "fallback reply"