# Environment variable contract

This project uses a single Django settings module and environment variables for runtime behavior.

## Core
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`

## Security / Proxy
- `CSRF_TRUSTED_ORIGINS`
- `CSRF_COOKIE_SECURE`
- `SESSION_COOKIE_SECURE`
- `DJANGO_BEHIND_PROXY`
- `DJANGO_SECURE_SSL_REDIRECT`
- `SECURE_HSTS_SECONDS`
- `SECURE_HSTS_INCLUDE_SUBDOMAINS`
- `SECURE_HSTS_PRELOAD`

## Database
- `DATABASE` (`postgresql` or `sqlite3`)
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`

## CORS
- `DJANGO_CORS_ALLOWED_ORIGINS`
- `DJANGO_CORS_ALLOWED_ORIGINS_REGEX`
- `DJANGO_CORS_ALLOW_ALL_ORIGINS`

## Email / transactional messaging
- `EMAIL_USE_CONSOLE_BACKEND` (defaults true only in local/dev-style environments)
- `EMAIL_BACKEND` (defaults to console in local/dev, Postmark backend elsewhere)
- `EMAIL_ENVIRONMENT_NAME` (e.g. `local`, `staging`, `production`)
- `EMAIL_BASE_URL` (defaults to `https://medsim.jackfruitco.com` for production-like, `https://medsim-staging.jackfruitco.com` for staging)
- `DEFAULT_FROM_EMAIL` (default: `MedSim by Jackfruit <noreply@jackfruitco.com>`)
- `EMAIL_REPLY_TO` (default: `support@jackfruitco.com`)
- `SERVER_EMAIL` (default: `errors@jackfruitco.com`)
- `EMAIL_SUBJECT_PREFIX`
- `EMAIL_STAGING_SUBJECT_PREFIX` (default: `[STAGING]`)
- `EMAIL_STAGING_BANNER_ENABLED`
- `ACCOUNT_DEFAULT_HTTP_PROTOCOL` (default: `https`)
- `POSTMARK_SERVER_TOKEN` (required for Postmark backend in non-local environments)
- `POSTMARK_MESSAGE_STREAM` (optional; useful for transactional stream routing)

## Tasks / Redis / Celery / Rate limits
- `REDIS_HOSTNAME`, `REDIS_PORT`, `REDIS_PASSWORD`
- `DJANGO_TASKS_MAX_RETRIES`, `DJANGO_TASKS_RETRY_DELAY`
- `CELERY_TASK_TIME_LIMIT`, `CELERY_TASK_SOFT_TIME_LIMIT`
- `RATE_LIMIT_AUTH_REQUESTS`, `RATE_LIMIT_MESSAGE_REQUESTS`, `RATE_LIMIT_API_REQUESTS`

## JWT
- `JWT_SECRET_KEY`
- `JWT_ACCESS_TOKEN_LIFETIME`
- `JWT_REFRESH_TOKEN_LIFETIME`

## Site metadata
- `SITE_NAME`
- `SITE_ADMIN_NAME`, `SITE_ADMIN_EMAIL`
- `APP_GIT_SHA` (optional backend commit SHA exposed by `/api/v1/build-info/`; `GIT_SHA` is accepted as a fallback)
- `APP_BUILD_TIME` (optional backend artifact build timestamp in UTC exposed by `/api/v1/build-info/`; `BUILD_TIME` is accepted as a fallback)

## Authentication / Social providers
- `ACCOUNT_SIGNUP_FIELDS`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`

## OrchestrAI / Observability
- `ORCA_DEFAULT_MODEL`
- `LOGFIRE_TOKEN`
