from django.conf import settings


def persist_raw_ai_requests() -> bool:
    return bool(settings.PRIVACY_PERSIST_RAW_AI_REQUESTS)


def persist_raw_ai_responses() -> bool:
    return bool(settings.PRIVACY_PERSIST_RAW_AI_RESPONSES)


def persist_ai_message_history() -> bool:
    return bool(settings.PRIVACY_PERSIST_AI_MESSAGE_HISTORY)


def persist_provider_raw() -> bool:
    return bool(settings.PRIVACY_PERSIST_PROVIDER_RAW)


def chat_retention_days() -> int:
    return int(settings.PRIVACY_CHAT_RETENTION_DAYS)


def raw_ai_retention_days() -> int:
    return int(settings.PRIVACY_RAW_AI_RETENTION_DAYS)


def derived_feedback_retention_days() -> int:
    return int(settings.PRIVACY_DERIVED_FEEDBACK_RETENTION_DAYS)


def pii_warning_enabled() -> bool:
    return bool(settings.PRIVACY_ENABLE_PII_WARNING)


def basic_pii_scan_enabled() -> bool:
    return bool(settings.PRIVACY_ENABLE_BASIC_PII_SCAN)


def analytics_enabled() -> bool:
    return bool(settings.PRIVACY_ANALYTICS_ENABLED)


def analytics_require_consent() -> bool:
    return bool(settings.PRIVACY_ANALYTICS_REQUIRE_CONSENT)
