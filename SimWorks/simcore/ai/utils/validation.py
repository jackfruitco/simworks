"""

"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Valid image formats for OpenAI API
# See https://platform.openai.com/docs/api-reference/images/create#images-create-output_format
OPENAI_VALID_FORMATS = {"png", "jpeg", "webp"}
DEFAULT_IMAGE_FORMAT = settings.OPENAI_DEFAULT_IMAGE_FORMAT or "webp"


def validate_image_format(_format: str) -> str:
    """
    Validates the given image format by ensuring it matches
    a predefined set of valid formats per OpenAI documentation.

    See https://platform.openai.com/docs/api-reference/images/create#images-create-output_format

    :param _format: The image format to be validated
    :type _format: str

    :raises ValueError: If the given format is invalid

    :return: The validated image format if valid, otherwise a default format
    :rtype: str
    """
    _format = _format.lower().strip()

    if _format not in OPENAI_VALID_FORMATS:
        raise ValueError(f"Invalid OpenAI image format: {_format} (must be one of {OPENAI_VALID_FORMATS}).")

    return _format