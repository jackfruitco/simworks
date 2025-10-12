import logging

from simcore.ai_v1.schemas import StrictOutputSchema

logger = logging.getLogger(__name__)


def maybe_parse_to_schema(text: str | dict, schema_cls: StrictOutputSchema) -> StrictOutputSchema | str:
    """Parse the given text it's Pydantic schema class."""
    try:
        return schema_cls.model_validate_json(text)
    except Exception as e:
        logger.warning(f"Failed to parse output to schema: {e}")
        return text