from orchestrai.types.tools import BaseLLMTool, LLMToolCall, LLMToolCallDelta


def test_base_llm_tool_holds_fields():
    tool = BaseLLMTool(name="demo", description="desc", input_schema={"type": "object"})
    assert tool.name == "demo"
    assert tool.input_schema["type"] == "object"


def test_llm_tool_call_round_trip():
    call = LLMToolCall(call_id="1", name="demo", arguments={"x": 1})
    assert call.call_id == "1"
    assert call.arguments["x"] == 1


def test_llm_tool_call_delta_partial_fields():
    delta = LLMToolCallDelta(name="demo")
    assert delta.name == "demo"
