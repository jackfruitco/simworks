"""Default configuration values for OrchestrAI."""

DEFAULTS: dict[str, object] = {
    "MODE": "single",
    "CLIENT": None,
    "CLIENTS": {},
    "PROVIDERS": {},
    "DISCOVERY_PATHS": (),
    "FIXUPS": (),
    "LOADER": "orchestrai.loaders.default:DefaultLoader",
}

