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
}
