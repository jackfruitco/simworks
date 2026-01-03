from pydantic import BaseModel

from orchestrai.types import ContentRole, Metafield, OutputTextContent, OutputItem

from .utils.schema_lint import find_open_objects


def test_metafield_schema_is_closed() -> None:
    schema = Metafield.model_json_schema()
    assert find_open_objects(schema) == []


def test_find_open_objects_detects_open_maps() -> None:
    class OpenMapModel(BaseModel):
        data: dict[str, str]

    schema = OpenMapModel.model_json_schema()
    assert "$/properties/data" in find_open_objects(schema)


def test_output_item_meta_defaults_to_empty_list() -> None:
    content = OutputTextContent(text="hello")
    item = OutputItem(role=ContentRole.ASSISTANT, content=[content])

    assert item.item_meta == []
    assert item.model_dump()["item_meta"] == []
