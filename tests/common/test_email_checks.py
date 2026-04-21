from django.core.checks import Error, Warning
from django.test import override_settings

from apps.common import checks


def _ids(results):
    return {result.id for result in results}


@override_settings(
    DEBUG=False,
    EMAIL_ENVIRONMENT_NAME="production",
    EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
    DEFAULT_FROM_EMAIL="MedSim by Jackfruit <noreply@jackfruitco.com>",
    EMAIL_REPLY_TO="support@jackfruitco.com",
    SERVER_EMAIL="errors@jackfruitco.com",
    EMAIL_BASE_URL="https://medsim.jackfruitco.com",
)
def test_email_checks_error_for_console_backend_in_non_dev_environment():
    results = checks.check_email_configuration(None)

    assert any(isinstance(result, Error) for result in results)
    assert "config.E014" in _ids(results)


@override_settings(
    DEBUG=False,
    EMAIL_ENVIRONMENT_NAME="staging",
    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST_USER="",
    EMAIL_HOST_PASSWORD="",
    DEFAULT_FROM_EMAIL="MedSim by Jackfruit <noreply@jackfruitco.com>",
    EMAIL_REPLY_TO="support@jackfruitco.com",
    SERVER_EMAIL="errors@jackfruitco.com",
    EMAIL_BASE_URL="https://medsim.jackfruitco.com",
)
def test_email_checks_error_for_missing_smtp_credentials():
    results = checks.check_email_configuration(None)

    assert "config.E015" in _ids(results)
    assert "config.E020" in _ids(results)
    assert any("SendGrid SMTP" in str(result.hint) for result in results)
    assert any("SendGrid API key" in str(result.hint) for result in results)


@override_settings(
    DEBUG=False,
    EMAIL_ENVIRONMENT_NAME="production",
    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST_USER="user@example.com",
    EMAIL_HOST_PASSWORD="secret",
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


@override_settings(
    DEBUG=False,
    EMAIL_ENVIRONMENT_NAME="production",
    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST="smtp.sendgrid.net",
    EMAIL_HOST_USER="user@example.com",
    EMAIL_HOST_PASSWORD="sendgrid-api-key",
    DEFAULT_FROM_EMAIL="MedSim by Jackfruit <noreply@jackfruitco.com>",
    EMAIL_REPLY_TO="support@jackfruitco.com",
    SERVER_EMAIL="errors@jackfruitco.com",
    EMAIL_BASE_URL="https://medsim.jackfruitco.com",
)
def test_email_checks_warn_for_sendgrid_smtp_username_override():
    results = checks.check_email_configuration(None)

    assert any(isinstance(result, Warning) and result.id == "config.W002" for result in results)
