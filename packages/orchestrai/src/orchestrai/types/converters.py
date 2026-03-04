# orchestrai/types/converters.py
"""
Converters between Build and Result types.

These utilities enable conversion between:
- Build* types (ergonomic construction with defaults)
- Result* types (strict validation/schema generation)

Conversion is typically lossless for the core data, though Build->Result
may fail validation if required fields are missing.
"""

from typing import Any

from .build import BuildMessageItem
from .build_content import (
    BuildAudioContent,
    BuildFileContent,
    BuildImageContent,
    BuildJsonContent,
    BuildScreenshotContent,
    BuildTextContent,
    BuildToolCallContent,
    BuildToolResultContent,
)
from .result import ResultMessageItem
from .result_content import (
    ResultAudioContent,
    ResultContent,
    ResultFileContent,
    ResultImageContent,
    ResultJsonContent,
    ResultScreenshotContent,
    ResultTextContent,
    ResultToolCallContent,
    ResultToolResultContent,
)

__all__ = (
    "build_content_to_result",
    "build_to_result",
    "result_content_to_build",
    "result_to_build",
)


def build_to_result(build_item: BuildMessageItem) -> ResultMessageItem:
    """
    Convert Build* message to Result* message for validation/persistence.

    Raises:
        ValidationError: If Build data doesn't meet Result* strictness requirements
    """
    return ResultMessageItem.model_validate(build_item.model_dump())


def result_to_build(result_item: ResultMessageItem) -> BuildMessageItem:
    """
    Convert Result* message to Build* message for manipulation.

    This is always safe since Result* is stricter than Build*.
    """
    return BuildMessageItem.model_validate(result_item.model_dump())


def build_content_to_result(build_content: Any) -> ResultContent:
    """
    Convert Build* content to Result* content.

    Type mapping:
    - BuildTextContent -> ResultTextContent
    - BuildImageContent -> ResultImageContent
    - etc.

    Raises:
        ValidationError: If Build data doesn't meet Result* requirements
    """
    # Pydantic will handle discriminated union validation
    if isinstance(build_content, BuildTextContent):
        return ResultTextContent.model_validate(build_content.model_dump())
    elif isinstance(build_content, BuildImageContent):
        return ResultImageContent.model_validate(build_content.model_dump())
    elif isinstance(build_content, BuildAudioContent):
        return ResultAudioContent.model_validate(build_content.model_dump())
    elif isinstance(build_content, BuildFileContent):
        return ResultFileContent.model_validate(build_content.model_dump())
    elif isinstance(build_content, BuildScreenshotContent):
        return ResultScreenshotContent.model_validate(build_content.model_dump())
    elif isinstance(build_content, BuildToolCallContent):
        return ResultToolCallContent.model_validate(build_content.model_dump())
    elif isinstance(build_content, BuildToolResultContent):
        return ResultToolResultContent.model_validate(build_content.model_dump())
    elif isinstance(build_content, BuildJsonContent):
        return ResultJsonContent.model_validate(build_content.model_dump())
    else:
        raise ValueError(f"Unknown build content type: {type(build_content)}")


def result_content_to_build(result_content: ResultContent) -> Any:
    """
    Convert Result* content to Build* content.

    Type mapping:
    - ResultTextContent -> BuildTextContent
    - ResultImageContent -> BuildImageContent
    - etc.
    """
    if isinstance(result_content, ResultTextContent):
        return BuildTextContent.model_validate(result_content.model_dump())
    elif isinstance(result_content, ResultImageContent):
        return BuildImageContent.model_validate(result_content.model_dump())
    elif isinstance(result_content, ResultAudioContent):
        return BuildAudioContent.model_validate(result_content.model_dump())
    elif isinstance(result_content, ResultFileContent):
        return BuildFileContent.model_validate(result_content.model_dump())
    elif isinstance(result_content, ResultScreenshotContent):
        return BuildScreenshotContent.model_validate(result_content.model_dump())
    elif isinstance(result_content, ResultToolCallContent):
        return BuildToolCallContent.model_validate(result_content.model_dump())
    elif isinstance(result_content, ResultToolResultContent):
        return BuildToolResultContent.model_validate(result_content.model_dump())
    elif isinstance(result_content, ResultJsonContent):
        return BuildJsonContent.model_validate(result_content.model_dump())
    else:
        raise ValueError(f"Unknown result content type: {type(result_content)}")
