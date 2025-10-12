import logging
from typing import List

logger = logging.getLogger(__name__)

async def get_output_type(output: dict[str, str]) -> str:
    from simai.models import ResponseType

    type_map = {
        "image_generation_call": ResponseType.MEDIA,
        "content": ResponseType.REPLY
    }

async def get_output_text(output: dict[str, str]) -> str:
    """
    Return string with all output text parts combined.

    Used to extract text from an OpenAI ResponseOutputItem with multiple content entries.

    :param output: The ResponseOutputItem to extract text from.
    :type output: dict[str, str]
    :return: The combined text from all content parts as a single String.
    """

    texts: List[str] = []
    for content in output.get("content", []):
        if content.type == "output_text":
            texts.append(content.text)

    return "".join(texts)

async def get_output_groups(output: dict[str, str]) -> dict[str, str]:
    if not isinstance(output, dict):
        raise ValueError(f"Invalid output: {output}")

    groups = {
        "messages": [],
        "metadata": {"patient_metadata": {}, "simulation_metadata": []}
    }

    # Add messages to messages group
    groups["messages"].extend(output.get("messages") or [])

    metadata = output.get("metadata") or {}
    groups["metadata"]["patient_metadata"].update(
        metadata.get("patient_metadata") or {}
    )

    groups["metadata"]["simulation_metadata"].extend(
        metadata.simulation_metadata or []
    )