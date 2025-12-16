"""Default configuration values for OrchestrAI."""

DEFAULTS: dict[str, object] = {
    "MODE": "single",
    "CLIENT": None,
    "CLIENTS": {},
    "PROVIDERS": {},
    "DISCOVERY_PATHS": (
        "orchestrai.contrib.provider_backends",
        "orchestrai.contrib.provider_codecs",
        "*.orca.services",
        "*.orca.output_schemas",
        "*.orca.codecs",
        "*.ai.services",
    ),
    "FIXUPS": (),
    "LOADER": "orchestrai.loaders.default:DefaultLoader",
    "IDENTITY_STRIP_TOKENS": tuple(),
    # Provider/backend defaults
    "PROVIDER_DEFAULT_TIMEOUT": 60,
    "PROVIDER_DEFAULT_MODEL": "gpt-4o-mini",
    "PROVIDER_DEFAULT_PROFILE": "default",
    # Client/runtime defaults
    "CLIENT_DEFAULT_TIMEOUT": None,
    "CLIENT_DEFAULT_MAX_RETRIES": 3,
    "CLIENT_DEFAULT_TELEMETRY_ENABLED": True,
    "CLIENT_DEFAULT_LOG_PROMPTS": False,
    "CLIENT_DEFAULT_RAISE_ON_ERROR": True,
}
