# orchestrai/conf/global_settings.py


# ---------------------------------------------------------------------------
# MODE
# ---------------------------------------------------------------------------
# Package-level default: single Orca mode.
# Project settings can override this. Strict mode logic lives in the
# Pydantic config layer (not here).
POD_MODE: bool = False

# ---------------------------------------------------------------------------
# PROVIDER DEFAULTS (PACKAGE-LEVEL)
# ---------------------------------------------------------------------------
# "provider alias" = index into PROVIDERS (e.g. "default").
# "backend identity" = dot-separated label in the provider backend registry
#                      (e.g. "openai.responses.backend").

# Raw providers config; projects normally override this via their own
# settings module. When empty, the config layer can auto-synthesize a
# "default" provider using DEFAULT_PROVIDER_BACKEND_IDENTITY.
PROVIDERS: dict = {}

# Default provider alias to use when nothing else is specified.
DEFAULT_PROVIDER: str = "default"

# Default API key alias to use inside PROVIDERS[alias].api_key_envvar
# when it is a dict. If api_key_envvar is a plain str, this is ignored.
DEFAULT_PROVIDER_API_KEY_ALIAS: str = "prod"

# Default provider profile alias (e.g. "default", "low_cost").
DEFAULT_PROVIDER_PROFILE: str = "default"

# Backend identity used when auto-synthesizing a "default" provider
# in minimal / single-Orca configurations.
DEFAULT_PROVIDER_BACKEND_IDENTITY: str = "openai.responses.backend"

# ---------------------------------------------------------------------------
# CLIENT DEFAULTS (PACKAGE-LEVEL)
# ---------------------------------------------------------------------------
# "client alias" = index into CLIENTS (e.g. "default", "low_cost").

# Raw clients config; projects can define CLIENTS in their settings.
# The config layer will validate this into a OrcaClientSettings model and
# always synthesize a baseline "default" client.
CLIENTS: dict = {}

# Alias of the client used when get_orca_client() is called without an
# explicit client argument. The synthetic baseline client is always
# called "default"; callers can change DEFAULT_CLIENT to point at
# another alias without overriding that baseline.
DEFAULT_CLIENT: str = "default"

# Package-level client behavior defaults; Pydantic models will use these
# when project settings don't override them.
CLIENT_DEFAULT_MAX_RETRIES: int = 3
CLIENT_DEFAULT_TIMEOUT_S: float | None = None
CLIENT_RAISE_ON_ERROR: bool = True
CLIENT_TELEMETRY_ENABLED: bool = True
CLIENT_LOG_PROMPTS: bool = False

# ---------------------------------------------------------------------------
# IDENTITY / DISCOVERY
# ---------------------------------------------------------------------------

# Tokens to strip when deriving identity labels globally. Decorators may
# also provide their own strip token lists.
ORCA_IDENTITY_STRIP_TOKENS: list[str] = []

DISCOVERY_PATHS: list[str] = [
    "orchestrai.contrib.provider_backends.openai",
    "orchestrai.contrib.provider_codecs.openai",
    "orchestrai.contrib.services",
    "orchestrai.contrib.codecs",
]

ENABLE_ENTRYPOINTS: bool = True

# ---------------------------------------------------------------------------
# BACKWARDS-COMPAT ALIASES (to be removed in a future minor release)
# ---------------------------------------------------------------------------
# These keep older code paths compiling while you finish the refactor.

# Old name for DEFAULT_PROVIDER_BACKEND_IDENTITY
DEFAULT_PROVIDER_IDENTITY = DEFAULT_PROVIDER_BACKEND_IDENTITY

# Old name for DEFAULT_CLIENT
DEFAULT_CLIENT_NAME = DEFAULT_CLIENT