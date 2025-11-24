# tests/types/test_dtos_content.py

import pytest
from pydantic import ValidationError

from simcore_ai.types.content import ContentRole
from simcore_ai.types.input import (
    InputContent,
    InputTextContent,
    InputImageContent,
    InputAudioContent,
    InputFileContent,
    InputScreenshotContent,
)
from simcore_ai.types.messages import InputItem, OutputItem
from simcore_ai.types.output import (
    OutputContent,
    OutputTextContent,
    OutputImageContent,
    OutputAudioContent,
    OutputFileContent,
    OutputScreenshotContent,
    OutputToolCallContent,
    OutputToolResultContent,
    OutputJsonContent,
)


def test_content_role_enum_values():
    assert ContentRole.USER.value == "user"
    assert ContentRole.ASSISTANT.value == "assistant"
    assert ContentRole.TOOL.value == "tool"


def test_output_text_content_basic():
    c = OutputTextContent(text="hello")
    assert c.type == "output_text"
    assert c.text == "hello"


# ---- Input Text / Image / Audio / File / Screenshot -------------------------------


def test_input_text_content_basic():
    c = InputTextContent(text="hello")
    assert c.type == "input_text"
    assert c.text == "hello"


def test_input_text_content_rejects_extra_fields():
    with pytest.raises(ValidationError):
        InputTextContent(text="hello", extra_field="nope")  # type: ignore[call-arg]


def test_input_image_content_basic():
    c = InputImageContent(mime_type="image/png", data_b64="AAA=")
    assert c.type == "input_image"
    assert c.mime_type == "image/png"
    assert c.data_b64 == "AAA="


def test_input_audio_content_basic():
    c = InputAudioContent(mime_type="audio/wav", data_b64="BBB=")
    assert c.type == "input_audio"
    assert c.mime_type == "audio/wav"
    assert c.data_b64 == "BBB="


def test_input_file_content_basic():
    c = InputFileContent(mime_type="application/pdf", data_b64="CCC=")
    assert c.type == "input_file"
    assert c.mime_type == "application/pdf"
    assert c.data_b64 == "CCC="


def test_input_screenshot_content_basic():
    c = InputScreenshotContent(mime_type="image/png", data_b64="DDD=")
    assert c.type == "computer_screenshot"
    assert c.mime_type == "image/png"
    assert c.data_b64 == "DDD="


# ---- Output Tool content ----------------------------------------------------------


def test_output_tool_content_defaults_and_shape():
    t = OutputToolCallContent(call_id="call-1", name="do_something")
    assert t.type == "tool_call"
    assert t.call_id == "call-1"
    assert t.name == "do_something"
    assert t.arguments == {}


def test_output_tool_content_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        OutputToolCallContent(call_id="call-1", name="do_something", foo="bar")  # type: ignore[call-arg]


def test_output_tool_result_content_allows_text_or_json_or_binary():
    t1 = OutputToolResultContent(call_id="call-1", result_text="ok")
    assert t1.result_text == "ok"
    assert t1.result_json is None
    assert t1.data_b64 is None

    t2 = OutputToolResultContent(call_id="call-2", result_json={"status": "ok"})
    assert t2.result_json == {"status": "ok"}

    t3 = OutputToolResultContent(call_id="call-3", mime_type="image/png", data_b64="EEE=")
    assert t3.mime_type == "image/png"
    assert t3.data_b64 == "EEE="


# ---- InputItem / OutputItem -------------------------------------------------------


def test_input_item_accepts_all_input_content_variants():
    contents: list[InputContent] = [
        InputTextContent(text="hello"),
        InputImageContent(mime_type="image/png", data_b64="AAA="),
        InputAudioContent(mime_type="audio/wav", data_b64="BBB="),
        InputFileContent(mime_type="application/pdf", data_b64="CCC="),
        InputScreenshotContent(mime_type="image/png", data_b64="DDD="),
    ]
    item = InputItem(role=ContentRole.USER, content=contents)
    assert item.role == ContentRole.USER
    assert len(item.content) == 5


def test_input_item_rejects_invalid_content_type():
    with pytest.raises(ValidationError):
        InputItem(role=ContentRole.USER, content=["not-a-content-object"])  # type: ignore[arg-type]


def test_output_item_accepts_output_content_variants():
    contents: list[OutputContent] = [
        OutputTextContent(text="hello"),
        OutputImageContent(mime_type="image/png", data_b64="AAA="),
        OutputAudioContent(mime_type="audio/wav", data_b64="BBB="),
        OutputFileContent(mime_type="application/pdf", data_b64="CCC="),
        OutputScreenshotContent(mime_type="image/png", data_b64="DDD="),
        OutputToolCallContent(call_id="id-1", name="do_it"),
        OutputToolResultContent(call_id="id-1", result_text="done"),
        OutputJsonContent(value={"foo": "bar"}),
    ]
    item = OutputItem(role=ContentRole.ASSISTANT, content=contents)
    assert item.role == ContentRole.ASSISTANT
    assert len(item.content) == 8
    assert item.item_meta == {}


def test_output_item_rejects_invalid_content_type():
    with pytest.raises(ValidationError):
        OutputItem(role=ContentRole.ASSISTANT, content=[123])  # type: ignore[list-item]


def test_output_item_rejects_extra_fields():
    with pytest.raises(ValidationError):
        OutputItem(
            role=ContentRole.ASSISTANT,
            content=[OutputTextContent(text="hi")],
            extra_field="nope",  # type: ignore[call-arg]
        )


def test_output_json_content_basic():
    c = OutputJsonContent(value={"foo": "bar"})
    assert c.type == "output_json"
    assert c.value == {"foo": "bar"}


def test_output_json_content_rejects_non_dict_value():
    with pytest.raises(ValidationError):
        OutputJsonContent(value="not-a-dict")  # type: ignore[arg-type]


def test_output_image_content_basic():
    c = OutputImageContent(mime_type="image/png", data_b64="AAA=")
    assert c.type == "output_image"
    assert c.mime_type == "image/png"
    assert c.data_b64 == "AAA="


def test_output_audio_content_basic():
    c = OutputAudioContent(mime_type="audio/wav", data_b64="BBB=")
    assert c.type == "output_audio"
    assert c.mime_type == "audio/wav"
    assert c.data_b64 == "BBB="


def test_output_file_content_basic():
    c = OutputFileContent(mime_type="application/pdf", data_b64="CCC=")
    assert c.type == "output_file"
    assert c.mime_type == "application/pdf"
    assert c.data_b64 == "CCC="


def test_output_screenshot_content_basic():
    c = OutputScreenshotContent(mime_type="image/png", data_b64="DDD=")
    assert c.type == "output_screenshot"
    assert c.mime_type == "image/png"
    assert c.data_b64 == "DDD="


def test_input_item_rejects_output_content_instance():
    with pytest.raises(ValidationError):
        InputItem(
            role=ContentRole.USER,
            content=[OutputTextContent(text="hi")],  # type: ignore[list-item]
        )


def test_output_item_rejects_input_content_instance():
    with pytest.raises(ValidationError):
        OutputItem(
            role=ContentRole.ASSISTANT,
            content=[InputTextContent(text="hi")],  # type: ignore[list-item]
        )
