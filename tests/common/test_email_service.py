from django.core import mail
from django.test import override_settings

from apps.common.emailing.service import send_transactional_email


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="MedSim by Jackfruit <noreply@jackfruitco.com>",
    EMAIL_REPLY_TO="support@jackfruitco.com",
    EMAIL_STAGING_SUBJECT_PREFIX="[STAGING]",
)
def test_send_transactional_email_applies_defaults_and_staging_prefix():
    sent = send_transactional_email(
        to=["clinician@example.com"],
        subject="Password reset",
        text_body="plain text",
        html_body="<p>plain text</p>",
        environment_hint="staging",
    )

    assert sent == 1
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.from_email == "MedSim by Jackfruit <noreply@jackfruitco.com>"
    assert message.reply_to == ["support@jackfruitco.com"]
    assert message.subject.startswith("[STAGING]")
    assert message.alternatives[0].mimetype == "text/html"

from django.test import RequestFactory

from apps.common.emailing.environment import get_email_base_url, is_staging_email_context


def test_environment_helpers_select_prod_url_from_request_host():
    request = RequestFactory().get("/", HTTP_HOST="medsim.jackfruitco.com")

    assert get_email_base_url(request) == "https://medsim.jackfruitco.com"
    assert is_staging_email_context(request) is False


def test_environment_helpers_select_staging_url_from_request_host():
    request = RequestFactory().get("/", HTTP_HOST="medsim-staging.jackfruitco.com")

    assert get_email_base_url(request) == "https://medsim-staging.jackfruitco.com"
    assert is_staging_email_context(request) is True
