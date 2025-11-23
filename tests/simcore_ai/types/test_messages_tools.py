# tests/types/test_dtos_tools.py

from simcore_ai.types.messages import ToolItem


def test_tool_item_defaults():
    t = ToolItem(kind="image_generation")
    assert t.kind == "image_generation"
    assert t.function is None
    assert t.arguments == {}


def test_tool_item_custom_arguments():
    t = ToolItem(kind="image_generation", function="gen", arguments={"prompt": "test"})
    assert t.arguments == {"prompt": "test"}
