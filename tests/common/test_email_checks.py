from django.core.checks import Error, Warning
from django.test import override_settings

from apps.common import checks


def _ids(results):
    return {result.id for result in results}


@override_settings(
    DEBUG=False,
    EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
    POSTMARK_SERVER_TOKEN="",
    DEFAULT_FROM_EMAIL="MedSim by Jackfruit <noreply@jackfruitco.com>",
    EMAIL_REPLY_TO="support@jackfruitco.com",
    SERVER_EMAIL="errors@jackfruitco.com",
    EMAIL_BASE_URL="https://medsim.jackfruitco.com",
)
def test_email_checks_error_for_console_backend_in_non_debug():
    results = checks.check_email_configuration(None)

    assert any(isinstance(result, Error) for result in results)
    assert "config.E014" in _ids(results)


@override_settings(
    DEBUG=False,
    EMAIL_BACKEND="anymail.backends.postmark.EmailBackend",
    POSTMARK_SERVER_TOKEN="",
    DEFAULT_FROM_EMAIL="MedSim by Jackfruit <noreply@jackfruitco.com>",
    EMAIL_REPLY_TO="support@jackfruitco.com",
    SERVER_EMAIL="errors@jackfruitco.com",
    EMAIL_BASE_URL="https://medsim.jackfruitco.com",
)
def test_email_checks_error_for_missing_postmark_token():
    results = checks.check_email_configuration(None)

    assert "config.E015" in _ids(results)


@override_settings(
    DEBUG=False,
    EMAIL_BACKEND="anymail.backends.postmark.EmailBackend",
    POSTMARK_SERVER_TOKEN="token",
    DEFAULT_FROM_EMAIL="broken",
    EMAIL_REPLY_TO="",
    SERVER_EMAIL="",
    EMAIL_BASE_URL="https://custom.example.com",
)
def test_email_checks_validate_sender_identity_and_warn_on_non_approved_host():
    results = checks.check_email_configuration(None)

    assert "config.E016" in _ids(results)
    assert "config.E017" in _ids(results)
    assert "config.E018" in _ids(results)
    assert any(isinstance(result, Warning) and result.id == "config.W001" for result in results)
