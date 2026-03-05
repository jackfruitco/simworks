# orchestrai_django/conf/defaults.py
"""
Django-specific default configuration for OrchestrAI.

These defaults override the core OrchestrAI defaults when running in a Django context.
The primary difference is namespacing: API key environment variables use the ORCA_ prefix
to avoid conflicts with other libraries or SDKs that might read standard env vars.

Layering order:
1. Core OrchestrAI defaults (e.g., OPENAI_API_KEY)
2. Django defaults (this file, e.g., ORCA_OPENAI_API_KEY)
3. User settings via ORCHESTRAI Django setting
"""

DJANGO_DEFAULTS: dict[str, object] = {
    # API key environment variable names (namespaced for Django)
    # These override the core defaults to use ORCA_ prefixed env vars,
    # keeping Django app configuration separate from SDK defaults.
    "API_KEY_ENVVARS": {
        "openai": "ORCA_OPENAI_API_KEY",
        "anthropic": "ORCA_ANTHROPIC_API_KEY",
        "google": "ORCA_GOOGLE_API_KEY",
        "gemini": "ORCA_GOOGLE_API_KEY",
        "groq": "ORCA_GROQ_API_KEY",
        "mistral": "ORCA_MISTRAL_API_KEY",
        "cohere": "ORCA_COHERE_API_KEY",
    },
}
