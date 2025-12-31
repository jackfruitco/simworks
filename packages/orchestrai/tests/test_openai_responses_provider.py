import pytest

from orchestrai.contrib.provider_backends.openai.openai import (
    OpenAIResponsesProvider,
    normalize_responses_output,
)


class _FakeContent:
    def __init__(self, text: str, content_type: str = "output_text"):
        self.text = text
        self.type = content_type


class _FakeMessage:
    def __init__(self, contents, message_type: str = "message"):
        self.content = contents
        self.type = message_type


class _FakeResponse:
    def __init__(self, output, model: str = "gpt-test", resp_id: str = "resp_1"):
        self.output = output
        self.model = model
        self.id = resp_id


class _UnknownOutput:
    def __init__(self, output_type: str = "image"):
        self.type = output_type


def test_normalize_responses_output_collects_message_text():
    message = _FakeMessage([_FakeContent("hello"), _FakeContent(" world", "text")])
    reasoning = _FakeMessage([], message_type="reasoning")
    unknown = _UnknownOutput("image_generation")
    text, passthrough, meta = normalize_responses_output(_FakeResponse([reasoning, message, unknown]))

    assert text == "hello world"
    assert passthrough == [unknown]
    assert meta == {"unhandled_items": ["image_generation"]}


@pytest.mark.asyncio
async def test_provider_adapts_responses_output_without_retrying_unknown(monkeypatch):
    provider = OpenAIResponsesProvider(alias="test", api_key="dummy", client=object())

    message = _FakeMessage([_FakeContent("Hello from responses")])
    reasoning = _FakeMessage([], message_type="ResponseReasoningItem")
    unknown = _UnknownOutput("unused_attachment")
    resp = _FakeResponse([message, reasoning, unknown], resp_id="resp_123")

    adapted = provider.adapt_response(resp)

    assert adapted.output[0].content[0].text == "Hello from responses"
    assert adapted.provider_meta["id"] == "resp_123"
    assert adapted.provider_meta.get("output_meta", {}).get("unhandled_items") == [
        "unused_attachment"
    ]
