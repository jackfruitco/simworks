# orchestrai/conf/settings_single.example.py
import os

# -------------------------
# MODE
# -------------------------
# Single Orca mode: one logical Orca client, no PROVIDERS/CLIENTS.
# STRICT MODE: If POD_MODE=False, PROVIDERS and CLIENTS must NOT be defined.
POD_MODE = False

# -------------------------
# SINGLE CLIENT CONFIG
# -------------------------
# This is a collapsed config that your Pydantic settings layer will
# internally normalize into a single provider + a single client.
#
# Env vars default to None; Pydantic models/global_settings provide
# actual defaults and casting.

CLIENT = {
    # Backend identity (dot-separated identity string in provider registry)
    # Example: "openai.responses.backend"
    "backend": "openai.responses.backend",

    # API key envvar:
    # - str: single API key envvar
    # - dict[str, str]: multiple envvars keyed by an opaque alias ("prod", "dev", "tenant1", etc.)
    #
    # Keys are *aliases*, not hard-coded environments; "dev"/"prod" are just examples.
    "api_key_envvar": {
        "prod": os.getenv("ORCA_PROVIDER_API_KEY", None),
        "dev": os.getenv("ORCA_PROVIDER_API_KEY_DEV", None),
    },
    # or, simpler:
    # "api_key_envvar": os.getenv("ORCA_PROVIDER_API_KEY", None),

    # Provider-side tunables (will become a single "default" profile internally).
    # Leave as None to let Pydantic/global_settings fill defaults.
    "model": os.getenv("ORCA_CLIENT_DEFAULT_MODEL", None),
    "temperature": os.getenv("ORCA_CLIENT_DEFAULT_TEMPERATURE", None),
    "max_output_tokens": os.getenv("ORCA_CLIENT_DEFAULT_MAX_OUTPUT_TOKENS", None),

    # Client-side behavior (timeouts, retries, logging).
    # Leave as None to let Pydantic/global_settings supply defaults.
    "timeout_s": os.getenv("ORCA_CLIENT_DEFAULT_TIMEOUT_S", None),
    "max_retries": os.getenv("ORCA_CLIENT_DEFAULT_MAX_RETRIES", None),

    # Booleans as strings or None; Pydantic will coerce.
    "raise_on_error": os.getenv("ORCA_CLIENT_RAISE_ON_ERROR", None),
    "telemetry_enabled": os.getenv("ORCA_CLIENT_TELEMETRY_ENABLED", None),
    "log_prompts": os.getenv("ORCA_CLIENT_LOG_PROMPTS", None),
}

# -------------------------
# DISCOVERY / IDENTITY
# -------------------------

# Tokens to strip when deriving identity labels; can be left empty.
SIMCORE_IDENTITY_STRIP_TOKENS = []

# Modules to scan for provider backends, codecs, services, etc.
DISCOVERY_PATHS = [
    "orchestrai.contrib.provider_backends.openai",
    "orchestrai.contrib.provider_codecs.openai",
    "orchestrai.contrib.services",
    "orchestrai.contrib.codecs",
]

# Whether to also load components via Python entry points, if defined.
ENABLE_ENTRYPOINTS = True