"""Built-in provider codecs shipped with OrchestrAI."""

# Import OpenAI codecs so they register with the global registry on module import.
# Additional provider codec packages can follow the same pattern.
from .openai import *  # noqa: F401,F403

__all__ = (
    "OpenAIResponsesJsonCodec",
)
