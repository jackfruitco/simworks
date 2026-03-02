"""Security, host, and proxy settings."""

from __future__ import annotations

from .settings_parsers import bool_from_env, csv_from_env, int_from_env

# Set Allowed Hosts
ALLOWED_HOSTS = csv_from_env("DJANGO_ALLOWED_HOSTS")

# CSRF Configuration
CSRF_TRUSTED_ORIGINS = csv_from_env("CSRF_TRUSTED_ORIGINS")

# Secure-by-default cookie settings; override via env for local HTTP development.
CSRF_COOKIE_SECURE = bool_from_env("CSRF_COOKIE_SECURE", default=True)
SESSION_COOKIE_SECURE = bool_from_env("SESSION_COOKIE_SECURE", default=True)

# Reverse-proxy / Cloudflare Tunnel settings
DJANGO_BEHIND_PROXY = bool_from_env("DJANGO_BEHIND_PROXY", default=False)
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https") if DJANGO_BEHIND_PROXY else None
)
USE_X_FORWARDED_HOST = True if DJANGO_BEHIND_PROXY else False

# Optional hardening (recommended for production behind TLS-terminating proxy)
SECURE_SSL_REDIRECT = bool_from_env("DJANGO_SECURE_SSL_REDIRECT", default=False)

# HSTS (enable only when your public site is always HTTPS)
SECURE_HSTS_SECONDS = int_from_env("SECURE_HSTS_SECONDS", default=0, minimum=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = bool_from_env("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = bool_from_env("SECURE_HSTS_PRELOAD", default=False)
