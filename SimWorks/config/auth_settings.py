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
ACCOUNT_EMAIL_VERIFICATION = "mandatory"

# Redirect URLs
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"

# Explicit rate limits for allauth endpoints (requests per time window)
ACCOUNT_RATE_LIMITS = {
    "login_failed": "5/5m",  # 5 failed attempts per 5 minutes per IP
    "login_attempt": "10/5m",  # 10 total login attempts per 5 minutes
    "signup": "5/1h",  # 5 signups per hour per IP
    "send_email": "3/5m",  # 3 email sends per 5 minutes per IP
    "change_password": "3/5m",  # 3 password changes per 5 minutes
    "password_reset": "3/5m",  # 3 password reset requests per 5 minutes per IP
    "reauthenticate": "10/5m",
    "confirm_login_code": "5/5m",
    "request_login_code": "3/5m",
    "confirm_signup": "10/5m",
    "manage_2fa": "10/5m",
}

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
