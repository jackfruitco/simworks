import pytest

from orchestrai.contrib.provider_backends.openai.openai import OpenAIResponsesProvider


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


@pytest.mark.asyncio
async def test_provider_adapts_responses_output_extracts_text():
    """Test that the provider correctly extracts text from message content."""
    provider = OpenAIResponsesProvider(alias="test", api_key="dummy", client=object())

    message = _FakeMessage([_FakeContent("Hello from responses")])
    reasoning = _FakeMessage([], message_type="ResponseReasoningItem")
    unknown = _UnknownOutput("unused_attachment")
    resp = _FakeResponse([message, reasoning, unknown], resp_id="resp_123")

    adapted = provider.adapt_response(resp)

    # Verify text extraction
    assert adapted.output[0].content[0].text == "Hello from responses"
    # Verify metadata
    assert adapted.provider_meta["id"] == "resp_123"
