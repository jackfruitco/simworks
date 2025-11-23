# tests/types/test_tools.py

import pytest
from pydantic import ValidationError

from simcore_ai.types.tools import (
    BaseLLMTool,
    LLMToolChoice,
    LLMToolCall,
    LLMToolCallDelta,
)


def test_base_llm_tool_minimal():
    tool = BaseLLMTool(name="image_gen")
    assert tool.name == "image_gen"
    assert tool.description is None
    assert tool.input_schema == {}
    assert tool.strict is None
    assert tool.examples == []
    assert tool.arguments == {}


def test_base_llm_tool_full_values():
    tool = BaseLLMTool(
        name="search",
        description="Search the web",
        input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        strict=True,
        examples=[{"q": "fever guidelines"}],
        arguments={"q": "pneumonia symptoms"},
    )

    assert tool.name == "search"
    assert tool.description == "Search the web"
    assert tool.input_schema["type"] == "object"
    assert tool.strict is True
    assert len(tool.examples) == 1
    assert tool.examples[0]["q"] == "fever guidelines"
    assert tool.arguments == {"q": "pneumonia symptoms"}


def test_base_llm_tool_rejects_extra_fields():
    with pytest.raises(ValidationError):
        BaseLLMTool(
            name="image_gen",
            description="Generate an image",
            foo="bar",  # extra
        )


def test_llm_tool_choice_literal_values():
    # These should be acceptable values for the alias
    choices: list[LLMToolChoice] = ["auto", "none", "specific-tool"]
    assert choices[0] == "auto"
    assert choices[1] == "none"
    assert choices[2] == "specific-tool"


def test_llm_tool_call_defaults():
    call = LLMToolCall(call_id="call-1", name="search")
    assert call.call_id == "call-1"
    assert call.name == "search"
    assert call.arguments == {}


def test_llm_tool_call_with_arguments():
    call = LLMToolCall(
        call_id="call-2",
        name="search",
        arguments={"q": "pneumonia symptoms", "limit": 5},
    )
    assert call.arguments["q"] == "pneumonia symptoms"
    assert call.arguments["limit"] == 5


def test_llm_tool_call_rejects_extra_fields():
    with pytest.raises(ValidationError):
        LLMToolCall(
            call_id="call-3",
            name="search",
            arguments={"q": "headache"},
            extra_field="nope",  # StrictBaseModel: should fail
        )


def test_llm_tool_call_delta_defaults():
    delta = LLMToolCallDelta()
    assert delta.call_id is None
    assert delta.name is None
    assert delta.arguments_delta_json is None


def test_llm_tool_call_delta_with_partial_updates():
    delta = LLMToolCallDelta(
        call_id="call-1",
        name="search",
        arguments_delta_json='{"q": "updated query"}',
    )
    assert delta.call_id == "call-1"
    assert delta.name == "search"
    assert delta.arguments_delta_json == '{"q": "updated query"}'


def test_llm_tool_call_delta_rejects_extra_fields():
    with pytest.raises(ValidationError):
        LLMToolCallDelta(
            call_id="call-1",
            name="search",
            arguments_delta_json="{}",
            extra_field="nope",  # StrictBaseModel should reject this
        )