"""Default configuration values for OrchestrAI."""

DEFAULTS: dict[str, object] = {
    "MODE": "single",
    "DISCOVERY_PATHS": (
        "*.orca.services",
        "*.orca.output_schemas",
        "*.orca.codecs",
        "*.orca.persist",
        "*.orca.persistence",
        "*.ai.services",
    ),
    "FIXUPS": (),
    "LOADER": "orchestrai.loaders.default:DefaultLoader",
    "IDENTITY_STRIP_TOKENS": tuple(),
    # Service defaults (Pydantic AI)
    "DEFAULT_TIMEOUT": 60,
    "DEFAULT_MODEL": "openai:gpt-4o-mini",
    "DEFAULT_MAX_RETRIES": 3,
}
