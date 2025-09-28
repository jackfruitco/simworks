# simcore/ai/providers/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator, Protocol, Any

from simcore.ai.schemas.normalized_types import NormalizedAIRequest, NormalizedAIResponse, NormalizedStreamChunk, \
    NormalizedAITool


class ProviderError(Exception):
    """Base exception for provider-level errors."""


class ProviderBase(ABC):
    """
    Abstract base class for all AI providers.
    Providers must implement synchronous (non-stream) and streaming request methods.
    """

    name: str
    description: str

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description

    @abstractmethod
    async def call(self, req: NormalizedAIRequest, timeout: float = None) -> NormalizedAIResponse: ...

    @abstractmethod
    async def stream(self, req: NormalizedAIRequest) -> AsyncIterator[NormalizedStreamChunk]: ...

    def __repr__(self) -> str:
        return f"<AIProvider {self.name}>"


class ToolAdapter(Protocol):
    def to_provider(self, tool: NormalizedAITool) -> Any: ...

    def from_provider(self, raw: Any) -> NormalizedAITool: ...
