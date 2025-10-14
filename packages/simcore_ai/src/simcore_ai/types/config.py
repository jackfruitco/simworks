# simcore_ai/types/config.py
from dataclasses import dataclass
from typing import Optional


@dataclass
class AIProviderConfig:
    """Connection-level configuration for a specific AI provider."""
    provider: str
    api_key: Optional[str]
    base_url: Optional[str] = None
    model: Optional[str] = None
    timeout_s: int = 60
    image_model: Optional[str] = None
    image_format: Optional[str] = None
    image_size: Optional[str] = None
    image_quality: Optional[str] = None
    image_output_compression: Optional[str] = None
    image_background: Optional[str] = None
    image_moderation: Optional[str] = None

    def __post_init__(self):
        masked_key = (
            f"{self.api_key[:3]}...{self.api_key[-3:]}"
            if self.api_key and len(self.api_key) > 6
            else "***" if self.api_key else None
        )
        self._repr = (
            f"<AIProviderConfig provider={self.provider!r}, model={self.model!r}, "
            f"base_url={self.base_url!r}, timeout={self.timeout_s}s, api_key={masked_key!r}>"
        )

    def __repr__(self):
        return self._repr


@dataclass(slots=True)
class AIClientConfig:
    """Runtime behavior configuration for the AI client."""
    max_retries: int = 2
    timeout_s: int = 60
    telemetry_enabled: bool = True
    log_prompts: bool = False
    raise_on_error: bool = True

    def __repr__(self):
        return (
            f"<AIClientConfig retries={self.max_retries}, timeout={self.timeout_s}, "
            f"telemetry={self.telemetry_enabled}, log_prompts={self.log_prompts}>"
        )