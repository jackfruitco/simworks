# tests/types/test_dtos_content.py

import pytest
from pydantic import ValidationError

from simcore_ai.types.content import TextContent, ImageContent, AudioContent, FileContent, ScreenshotContent, \
    ToolContent, ToolResultContent
from simcore_ai.types import ContentRole, InputContent, OutputContent, InputItem, OutputItem


def test_content_role_enum_values():
    assert ContentRole.USER.value == "user"
    assert ContentRole.ASSISTANT.value == "assistant"
    assert ContentRole.TOOL.value == "tool"


# ---- Text / Image / Audio / File / Screenshot ---------------------------------------


def test_text_content_basic():
    c = TextContent(text="hello")
    assert c.type == "input_text"
    assert c.text == "hello"


def test_text_content_rejects_extra_fields():
    with pytest.raises(ValidationError):
        TextContent(text="hello", extra_field="nope")


def test_image_content_basic():
    c = ImageContent(mime_type="image/png", data_b64="AAA=")
    assert c.type == "input_image"
    assert c.mime_type == "image/png"
    assert c.data_b64 == "AAA="


def test_audio_content_basic():
    c = AudioContent(mime_type="audio/wav", data_b64="BBB=")
    assert c.type == "input_audio"
    assert c.mime_type == "audio/wav"
    assert c.data_b64 == "BBB="


def test_file_content_basic():
    c = FileContent(mime_type="application/pdf", data_b64="CCC=")
    assert c.type == "input_file"
    assert c.mime_type == "application/pdf"
    assert c.data_b64 == "CCC="


def test_screenshot_content_basic():
    c = ScreenshotContent(mime_type="image/png", data_b64="DDD=")
    assert c.type == "computer_screenshot"
    assert c.mime_type == "image/png"
    assert c.data_b64 == "DDD="


# ---- Tool content -------------------------------------------------------------------


def test_tool_content_defaults_and_shape():
    t = ToolContent(call_id="call-1", name="do_something")
    assert t.type == "tool_call"
    assert t.call_id == "call-1"
    assert t.name == "do_something"
    assert t.arguments == {}


def test_tool_content_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ToolContent(call_id="call-1", name="do_something", foo="bar")


def test_tool_result_content_allows_text_or_json_or_binary():
    t1 = ToolResultContent(call_id="call-1", result_text="ok")
    assert t1.result_text == "ok"
    assert t1.result_json is None
    assert t1.data_b64 is None

    t2 = ToolResultContent(call_id="call-2", result_json={"status": "ok"})
    assert t2.result_json == {"status": "ok"}

    t3 = ToolResultContent(call_id="call-3", mime_type="image/png", data_b64="EEE=")
    assert t3.mime_type == "image/png"
    assert t3.data_b64 == "EEE="


# ---- InputItem / OutputItem ---------------------------------------------------------


def test_input_item_accepts_all_input_content_variants():
    contents: list[InputContent] = [
        TextContent(text="hello"),
        ImageContent(mime_type="image/png", data_b64="AAA="),
        AudioContent(mime_type="audio/wav", data_b64="BBB="),
        FileContent(mime_type="application/pdf", data_b64="CCC="),
        ScreenshotContent(mime_type="image/png", data_b64="DDD="),
    ]
    item = InputItem(role=ContentRole.USER, content=contents)
    assert item.role == ContentRole.USER
    assert len(item.content) == 5


def test_input_item_rejects_invalid_content_type():
    with pytest.raises(ValidationError):
        InputItem(role=ContentRole.USER, content=["not-a-content-object"])  # type: ignore[arg-type]


def test_output_item_accepts_output_content_variants():
    contents: list[OutputContent] = [
        TextContent(text="hello"),
        ToolContent(call_id="id-1", name="do_it"),
        ToolResultContent(call_id="id-1", result_text="done"),
        ImageContent(mime_type="image/png", data_b64="AAA="),
        AudioContent(mime_type="audio/wav", data_b64="BBB="),
    ]
    item = OutputItem(role=ContentRole.ASSISTANT, content=contents)
    assert item.role == ContentRole.ASSISTANT
    assert len(item.content) == 5
    assert item.item_meta == {}


def test_output_item_rejects_invalid_content_type():
    with pytest.raises(ValidationError):
        OutputItem(role=ContentRole.ASSISTANT, content=[123])  # type: ignore[list-item]


def test_output_item_rejects_extra_fields():
    with pytest.raises(ValidationError):
        OutputItem(
            role=ContentRole.ASSISTANT,
            content=[TextContent(text="hi")],
            extra_field="nope",
        )