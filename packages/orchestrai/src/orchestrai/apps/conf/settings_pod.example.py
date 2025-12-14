# orchestrai/conf/settings_pod.example.py
import os

# -------------------------
# MODE
# -------------------------
# Pod mode: multi-provider / multi-client.
# STRICT MODE: If POD_MODE=True, CLIENT must NOT be defined.
POD_MODE = True

# -------------------------
# PROVIDERS (required)
# -------------------------
# PROVIDERS defines provider aliases and their backend identities,
# API key envvars, and profiles (model/temperature/max_tokens/etc.).
#
# "provider alias" = key in PROVIDERS (e.g. "default", "openai_prod").
# "backend identity" = dot-separated registry label (e.g. "openai.responses.backend").

PROVIDERS = {
    # Provider alias
    "default": {
        # Backend identity (dot-separated registry identity)
        "backend": "openai.responses.backend",

        # API key envvar:
        # - str: single envvar name
        # - dict[str, str|None]: envvar names keyed by opaque aliases ("prod", "dev", "tenant1").
        #
        # Keys are purely aliases. "prod"/"dev" are just examples.
        "api_key_envvar": {
            "prod": os.getenv("ORCA_PROVIDER_API_KEY", None),
            "dev": os.getenv("ORCA_PROVIDER_API_KEY_DEV", None),
        },
        # or:
        # "api_key_envvar": os.getenv("ORCA_PROVIDER_API_KEY", None),

        # Profiles: provider-side tuning presets.
        # Each profile is keyed by a profile alias ("default", "low_cost", etc.).
        "profiles": {
            "default": {
                "model": os.getenv("ORCA_CLIENT_DEFAULT_MODEL", None),
                "temperature": os.getenv("ORCA_CLIENT_DEFAULT_TEMPERATURE", None),
                "max_output_tokens": os.getenv("ORCA_CLIENT_DEFAULT_MAX_OUTPUT_TOKENS", None),
                # Provider-specific knobs can go here (e.g. "response_format", "top_p", etc.)
            },
            "low_cost": {
                "model": os.getenv("ORCA_CLIENT_LOW_COST_MODEL", None),
                "temperature": os.getenv("ORCA_CLIENT_LOW_COST_TEMPERATURE", None),
                "max_output_tokens": os.getenv("ORCA_CLIENT_LOW_COST_MAX_OUTPUT_TOKENS", None),
            },
            "images": {
                "model": os.getenv("ORCA_CLIENT_IMAGE_MODEL", None),
                "output_format": os.getenv("ORCA_CLIENT_IMAGE_OUTPUT_FORMAT", None),
            },
        },

        # Provider-level defaults.
        # "profile" should match one of the profile aliases above.
        "defaults": {
            "profile": os.getenv("ORCA_PROVIDER_DEFAULT_PROFILE", "default"),
        },
    },

    # Example of a second provider:
    # "anthropic": {
    #     "backend": "anthropic.responses.backend",
    #     "api_key_envvar": os.getenv("ANTHROPIC_API_KEY", None),
    #     "profiles": {
    #         "default": { "model": os.getenv("ANTHROPIC_DEFAULT_MODEL", None) },
    #     },
    #     "defaults": {
    #         "profile": "default",
    #     },
    # },
}

# -------------------------
# CLIENTS (optional presets)
# -------------------------
# CLIENTS defines logical Orca clients.
#
# "client alias" = key in CLIENTS (e.g. "low_cost", "safety_audit").
#
# STRICT MODE:
# - "default" is reserved for the auto-configured baseline client and MUST NOT
#   appear here. Use DEFAULT_CLIENT to point at a different client alias if you
#   want that as the default.

CLIENTS = {
    # Example: a low-cost client preset
    "low_cost": {
        # Provider alias to use for this client.
        # If omitted, DEFAULT_PROVIDER will be used.
        # "provider": "default",

        # Which API key alias to use from PROVIDERS[provider].api_key_envvar
        # If PROVIDERS[provider].api_key_envvar is a simple str, this is ignored.
        "api_key_alias": os.getenv("ORCA_LOW_COST_API_KEY_ALIAS", None),  # e.g. "dev" or "prod"

        # Which provider profile alias to use (e.g. "low_cost", "default").
        # If omitted, DEFAULT_PROVIDER_PROFILE or provider.defaults.profile will be used.
        "profile": os.getenv("ORCA_LOW_COST_PROFILE_ALIAS", "low_cost"),

        # Client-side behavior overrides.
        "timeout_s": os.getenv("ORCA_LOW_COST_TIMEOUT_S", None),
        "max_retries": os.getenv("ORCA_LOW_COST_MAX_RETRIES", None),
        "raise_on_error": os.getenv("ORCA_LOW_COST_RAISE_ON_ERROR", None),
        "telemetry_enabled": os.getenv("ORCA_LOW_COST_TELEMETRY_ENABLED", None),
        "log_prompts": os.getenv("ORCA_LOW_COST_LOG_PROMPTS", None),
    },

    # Example: a safety/audit client using a different provider
    # "safety_audit": {
    #     "provider": "anthropic",
    #     "api_key_alias": None,        # use default for that provider
    #     "profile": "default",
    #     "timeout_s": os.getenv("ORCA_SAFETY_TIMEOUT_S", None),
    #     "max_retries": os.getenv("ORCA_SAFETY_MAX_RETRIES", None),
    #     "raise_on_error": os.getenv("ORCA_SAFETY_RAISE_ON_ERROR", None),
    #     "telemetry_enabled": os.getenv("ORCA_SAFETY_TELEMETRY_ENABLED", None),
    #     "log_prompts": os.getenv("ORCA_SAFETY_LOG_PROMPTS", None),
    # },
}

# -------------------------
# GLOBAL DEFAULTS / POINTERS
# -------------------------
# These are POINTERS into the aliases above.
# Pydantic/global_settings should validate them against PROVIDERS/CLIENTS.

# Which provider alias to use if none is specified and the client doesn't override.
DEFAULT_PROVIDER = os.getenv("ORCA_DEFAULT_PROVIDER_ALIAS", "default")

# Which API key alias to use inside PROVIDERS[provider].api_key_envvar.
# If api_key_envvar is a str for that provider, this is ignored.
DEFAULT_PROVIDER_API_KEY_ALIAS = os.getenv("ORCA_DEFAULT_API_KEY_ALIAS", "prod")

# Which provider profile alias to use by default.
DEFAULT_PROVIDER_PROFILE = os.getenv("ORCA_DEFAULT_PROVIDER_PROFILE", "default")

# Which client alias to use when get_orca_client() is called without a client argument.
# "default" is the reserved auto-configured baseline client, synthesized from DEFAULT_*
# and PROVIDERS[DEFAULT_PROVIDER]. You can point this at another alias if you want:
# e.g. DEFAULT_CLIENT = "low_cost"
DEFAULT_CLIENT = os.getenv("ORCA_DEFAULT_CLIENT_ALIAS", "default")

# -------------------------
# DISCOVERY / IDENTITY
# -------------------------

SIMCORE_IDENTITY_STRIP_TOKENS = []

DISCOVERY_PATHS = [
    "orchestrai.contrib.provider_backends.openai",
    "orchestrai.contrib.provider_codecs.openai",
    "orchestrai.contrib.services",
    "orchestrai.contrib.codecs",
]

ENABLE_ENTRYPOINTS = True