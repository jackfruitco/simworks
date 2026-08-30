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
- `EMAIL_BACKEND` (defaults to console in local/dev, SMTP backend elsewhere)
- `EMAIL_HOST` (default: `smtp.sendgrid.net`)
- `EMAIL_PORT` (default: `587`)
- `EMAIL_USE_TLS` (default: `true`)
- `EMAIL_USE_SSL` (default: `false`)
- `EMAIL_HOST_USER` (default: `apikey` when SMTP backend is active)
- `EMAIL_HOST_PASSWORD` (SendGrid API key)
- `EMAIL_ENVIRONMENT_NAME` (e.g. `local`, `staging`, `production`)
- `EMAIL_BASE_URL` (defaults to `https://medsim.jackfruitco.com` for production-like, `https://medsim-staging.jackfruitco.com` for staging)
- `DEFAULT_FROM_EMAIL` (default: `MedSim by Jackfruit <noreply@jackfruitco.com>`)
- `EMAIL_REPLY_TO` (default: `support@jackfruitco.com`)
- `SERVER_EMAIL` (default: `errors@jackfruitco.com`)
- `EMAIL_SUBJECT_PREFIX`
- `EMAIL_STAGING_SUBJECT_PREFIX` (default: `[STAGING]`)
- `ACCOUNT_DEFAULT_HTTP_PROTOCOL` (default: `https`)

Current low-volume staging/production transport is SendGrid SMTP through Django's SMTP backend abstraction. The app-level email service and auth-email templates remain provider-agnostic so future provider migration stays mostly a backend/config swap.

Staging SendGrid SMTP values:

- `EMAIL_ENVIRONMENT_NAME=staging`
- `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`
- `EMAIL_HOST=smtp.sendgrid.net`
- `EMAIL_PORT=587`
- `EMAIL_USE_TLS=true`
- `EMAIL_USE_SSL=false`
- `EMAIL_HOST_USER=apikey`
- `EMAIL_HOST_PASSWORD=<SendGrid API key>`
- `EMAIL_BASE_URL=https://medsim-staging.jackfruitco.com`

Sender identity defaults may be omitted if the defaults are acceptable:

- `DEFAULT_FROM_EMAIL="MedSim by Jackfruit <noreply@jackfruitco.com>"`
- `EMAIL_REPLY_TO=support@jackfruitco.com`
- `SERVER_EMAIL=errors@jackfruitco.com`

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
- `ORCA_OPENAI_API_KEY` (preferred namespaced OpenAI key for OrchestrAI-backed app features)
- `OPENAI_API_KEY` (optional standard SDK-style alias; used when set, with `ORCA_OPENAI_API_KEY` as the fallback)
- `ORCA_DEFAULT_MODEL`
- `VOICELAB_REALTIME_MODEL` (default `gpt-realtime-2.1`)
- `VOICELAB_REALTIME_VOICE` (default `marin`)
- `VOICELAB_TRANSCRIPTION_MODEL` (default `gpt-4o-mini-transcribe`)
- `VOICELAB_BOOTSTRAP_MAX_TOKENS` (default `6000`; deterministic newest-history selection with a compact summary for omitted messages)
- `OPENAI_API_BASE_URL` (default `https://api.openai.com/v1`)
- `OPENAI_CONVERSATION_TIMEOUT_SECONDS` (default `10`)
- `VOICELAB_OPENAI_CLIENT_SECRETS_URL` (default `https://api.openai.com/v1/realtime/client_secrets`)
- `VOICELAB_OPENAI_CALLS_URL` (default `https://api.openai.com/v1/realtime/calls`)
- `VOICELAB_OPENAI_WEBSOCKET_URL` (default `wss://api.openai.com/v1/realtime`)
- `TRAINERLAB_RUNTIME_DEBOUNCE_SECONDS` (default `2.0`): batches rapid user interventions into one runtime turn request.
- `TRAINERLAB_RUNTIME_MIN_INTERVAL_SECONDS` (default `8.0`): prevents run/tick and scheduled progression triggers from spamming runtime turns.
- `TRAINERLAB_RUNTIME_MAX_CHAINED_TURNS` (default `2`): caps immediate recursive runtime follow-ups while preserving pending work with a delayed continuation.
- `LOGFIRE_TOKEN`
