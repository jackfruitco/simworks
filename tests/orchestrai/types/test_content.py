from orchestrai.types.content import (
    BaseTextContent,
    BaseToolResultContent,
    ContentRole,
)
from orchestrai.types.messages import InputItem, OutputItem


def test_text_content_round_trip():
    content = BaseTextContent(text="hello")
    assert content.text == "hello"


def test_output_tool_result_content_defaults():
    result = BaseToolResultContent(call_id="abc", mime_type="text/plain", data_b64="ZGF0YQ==")
    assert result.call_id == "abc"
    assert result.mime_type == "text/plain"


def test_message_wrappers_accept_content():
    inp = InputItem(role=ContentRole.USER, content=[BaseTextContent(text="hi")])
    out = OutputItem(role=ContentRole.ASSISTANT, content=[BaseTextContent(text="ok")])
    assert inp.role == ContentRole.USER
    assert out.role == ContentRole.ASSISTANT
