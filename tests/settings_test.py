from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "test"
DEBUG = True
JWT_SECRET_KEY = "test-jwt-secret-key-for-tests"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "django.contrib.sites",
    "orchestrai_django",  # core package under test
    # SimWorks apps for integration tests
    "apps.accounts",
    "apps.billing",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.apple",
    "allauth.socialaccount.providers.google",
    "apps.common",
    "apps.simcore",
    "apps.guards",
    "apps.chatlab",
    "apps.privacy",
    "apps.trainerlab",
    "channels",  # For WebSocket support
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
AUTH_USER_MODEL = "accounts.User"
SITE_ID = 1
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# URL configuration
ROOT_URLCONF = "config.urls"

# Middleware configuration
MIDDLEWARE = [
    "apps.common.middleware.HealthCheckMiddleware",
    "apps.common.middleware.CorrelationIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Template configuration (minimal for tests)
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "SimWorks" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.privacy.context_processors.privacy_flags",
            ],
        },
    },
]

PRIVACY_ENABLE_PII_WARNING = True
PRIVACY_ENABLE_BASIC_PII_SCAN = True
PRIVACY_CHAT_RETENTION_DAYS = 30
PRIVACY_RAW_AI_RETENTION_DAYS = 14
PRIVACY_DERIVED_FEEDBACK_RETENTION_DAYS = 3650
PRIVACY_PERSIST_RAW_AI_REQUESTS = False
PRIVACY_PERSIST_RAW_AI_RESPONSES = False
PRIVACY_PERSIST_AI_MESSAGE_HISTORY = False
PRIVACY_PERSIST_PROVIDER_RAW = False
PRIVACY_ANALYTICS_ENABLED = False
PRIVACY_ANALYTICS_REQUIRE_CONSENT = True
PRIVACY_DELETE_EXPORT_TOKEN_TTL_SECONDS = 600

# Channels configuration for WebSocket tests
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# Mirror production allauth behavior for email-only user model.
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = "email"

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": "test-google-client-id",
            "secret": "test-google-secret",
            "key": "",
        }
    },
    "apple": {
        "APP": {
            "client_id": "test-apple-client-id",
            "secret": "test-apple-team-id",
            "key": "test-apple-key-id",
            "settings": {
                "certificate_key": "test-apple-private-key",
            },
        }
    },
}

BILLING_STRIPE_PRICE_PLAN_MAP = {}
BILLING_APPLE_PRODUCT_PLAN_MAP = {}
BILLING_STRIPE_WEBHOOK_SECRET = "test-stripe-webhook-secret"
BILLING_STRIPE_SECRET_KEY = "test-stripe-secret"
BILLING_STRIPE_CHECKOUT_ENABLED = False

ACCOUNT_ADAPTER = "apps.accounts.adapters.InvitationAccountAdapter"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "MedSim by Jackfruit <noreply@jackfruitco.com>"
EMAIL_REPLY_TO = "support@jackfruitco.com"
SERVER_EMAIL = "errors@jackfruitco.com"
EMAIL_STAGING_SUBJECT_PREFIX = "[STAGING]"
EMAIL_BASE_URL = "https://medsim.jackfruitco.com"
EMAIL_ENVIRONMENT_NAME = "production"
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"
