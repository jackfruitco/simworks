"""Authentication and social-login settings."""

import os

from .settings_parsers import csv_from_env

# ---------------------------------------------------------------------------
# Django-allauth Configuration
# ---------------------------------------------------------------------------
SITE_ID = 1

# Custom adapter and forms for invitation-based signup
ACCOUNT_ADAPTER = "apps.accounts.adapters.InvitationAccountAdapter"
ACCOUNT_FORMS = {
    "signup": "apps.accounts.forms.InvitationSignupForm",
}

# Authentication settings
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = csv_from_env(
    "ACCOUNT_SIGNUP_FIELDS",
    default=["email*", "password1*", "password2*"],
)
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = "optional"  # Can be 'mandatory', 'optional', or 'none'

# Redirect URLs
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"

# Social authentication provider configuration
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": [
            "profile",
            "email",
        ],
        "AUTH_PARAMS": {
            "access_type": "online",
        },
        "APP": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
            "secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
            "key": "",
        },
    },
    "apple": {
        "APP": {
            # Service ID (Services ID from Apple Developer Console)
            "client_id": os.getenv("APPLE_CLIENT_ID", ""),
            # Team ID used by this deployment flow as the provider "secret" value.
            # Keep env name explicit to avoid confusion with Apple private key/JWT secret.
            "secret": os.getenv("APPLE_TEAM_ID", ""),
            # Key ID
            "key": os.getenv("APPLE_KEY_ID", ""),
            "settings": {
                # Private key content (from .p8 file)
                "certificate_key": os.getenv("APPLE_PRIVATE_KEY", ""),
            },
        },
    },
}
