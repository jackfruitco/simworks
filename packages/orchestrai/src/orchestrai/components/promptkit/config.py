# orchestrai/components/promptkit/config.py
from typing import Literal
from pydantic import BaseModel, HttpUrl, SecretStr

class ProviderCfg(BaseModel):
    """
    Fully-resolved backend config for a single instance.

    This is AFTER env/profile selection and env var resolution.
    """
    identity: str  # or your Identity type if you want
    environment: str  # "prod", "dev", "sandbox", etc.
    profile: str      # "default", "low_cost", etc.

    api_key: SecretStr
    base_url: HttpUrl | str
    timeout_s: float | None = None

    # Optional “knobs” – you can push some up to the client later if you want
    default_model: str | None = None
    default_temperature: float | None = None
    max_output_tokens: int | None = None

    # Free-form backend-specific extras
    extras: dict[str, object] = {}