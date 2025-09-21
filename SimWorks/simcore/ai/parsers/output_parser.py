import logging
from ..schemas.normalized_types import OutputSchemaType

logger = logging.getLogger(__name__)


def maybe_parse_to_schema(text: str | dict, schema_cls: OutputSchemaType) -> OutputSchemaType | str:
    """Parse the given text it's Pydantic schema class."""
    try:
        return schema_cls.model_validate_json(text)
    except Exception as e:
        logger.warning(f"Failed to parse output to schema: {e}")
        return text