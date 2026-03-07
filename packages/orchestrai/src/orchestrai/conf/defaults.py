"""Default configuration values for OrchestrAI."""

DEFAULTS: dict[str, object] = {
    "MODE": "single",
    "DISCOVERY_PATHS": (
        "*.orca.services",
        "*.orca.instructions",
        "*.orca.output_schemas",
        "*.orca.persist",
        "*.orca.persistence",
        "*.ai.services",
    ),
    "FIXUPS": (),
    "LOADER": "orchestrai.loaders.default:DefaultLoader",
    "IDENTITY_STRIP_TOKENS": (),
    # Service defaults (Pydantic AI)
    "DEFAULT_TIMEOUT": 60,
    "DEFAULT_MODEL": "openai-responses:gpt-5-nano",
    "DEFAULT_MAX_RETRIES": 3,
    # API key environment variable names (standard provider defaults)
    # These map provider names to the environment variable containing the API key.
    # OrchestrAI Django overrides these with ORCA_ prefixed variants.
    "API_KEY_ENVVARS": {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "groq": "GROQ_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "cohere": "COHERE_API_KEY",
    },
}
