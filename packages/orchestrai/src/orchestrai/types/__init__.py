# orchestrai/types/__init__.py
from .content import *
from .base import *
from .messages import *
from .transport import *
from .tools import *
from .input import *
from .output import *
from .meta import *

# New Build/Result pattern types
from .build import *
from .build_content import *
from .result import *
from .result_content import *
from .converters import *

__all__ = [
    "StrictBaseModel",

    "Request",
    "Response",
    "StreamChunk",

    "Boolish",
    "BaseLLMTool",
    "ContentRole",

    # Metadata for OpenAI strict mode compliance
    "Metafield",
    "HasItemMeta",

    # Legacy Input/Output types (deprecated - use Build*/Result* instead)
    "InputItem",
    "InputContent",
    "InputTextContent",
    "InputImageContent",
    "InputAudioContent",

    "OutputItem",
    "OutputContent",
    "OutputTextContent",
    "OutputImageContent",
    "OutputAudioContent",
    "OutputJsonContent",
    "OutputToolCallContent",
    "OutputToolResultContent",

    # Build types (for construction - ergonomic, with defaults)
    "BuildMessageItem",
    "BuildMetafield",
    "BuildContent",
    "BuildTextContent",
    "BuildImageContent",
    "BuildAudioContent",
    "BuildFileContent",
    "BuildScreenshotContent",
    "BuildToolCallContent",
    "BuildToolResultContent",
    "BuildJsonContent",

    # Result types (for schemas - strict, no defaults)
    "ResultMessageItem",
    "ResultMetafield",
    "ResultContent",
    "ResultTextContent",
    "ResultImageContent",
    "ResultAudioContent",
    "ResultFileContent",
    "ResultScreenshotContent",
    "ResultToolCallContent",
    "ResultToolResultContent",
    "ResultJsonContent",

    # Converters
    "build_to_result",
    "result_to_build",
    "build_content_to_result",
    "result_content_to_build",

    # Tools
    "BaseLLMTool",
    "LLMToolCall",
    "UsageContent",
]
