from django.core import mail
from django.test import RequestFactory, override_settings

from apps.common.emailing.environment import (
    get_email_base_url,
    get_email_environment_label,
    is_staging_email_context,
)
from apps.common.emailing.service import _build_standard_context, send_transactional_email
from apps.common.emailing.tasks import send_templated_email_task


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


def test_environment_helper_staging_hint_without_request_uses_staging_url():
    assert (
        get_email_base_url(environment_hint="staging") == "https://medsim-staging.jackfruitco.com"
    )
    assert get_email_environment_label(environment_hint="staging") == "staging"
    assert is_staging_email_context(environment_hint="staging") is True


def test_environment_helper_production_hint_without_request_uses_production_url():
    assert get_email_base_url(environment_hint="production") == "https://medsim.jackfruitco.com"
    assert get_email_environment_label(environment_hint="production") == "production"
    assert is_staging_email_context(environment_hint="production") is False


def test_environment_helpers_select_prod_url_from_request_host():
    request = RequestFactory().get("/", HTTP_HOST="medsim.jackfruitco.com")

    assert get_email_base_url(request=request) == "https://medsim.jackfruitco.com"
    assert is_staging_email_context(request=request) is False


def test_environment_helpers_select_staging_url_from_request_host():
    request = RequestFactory().get("/", HTTP_HOST="medsim-staging.jackfruitco.com")

    assert get_email_base_url(request=request) == "https://medsim-staging.jackfruitco.com"
    assert is_staging_email_context(request=request) is True


@override_settings(
    EMAIL_ENVIRONMENT_NAME="staging",
    EMAIL_BASE_URL="https://custom-staging.example.com",
)
def test_environment_helper_uses_custom_base_url_for_matching_settings_environment():
    assert get_email_base_url(environment_hint="staging") == "https://custom-staging.example.com"


@override_settings(
    EMAIL_ENVIRONMENT_NAME="staging",
    EMAIL_BASE_URL="https://medsim.jackfruitco.com",
)
def test_environment_helper_ignores_opposite_canonical_base_url():
    assert (
        get_email_base_url(environment_hint="staging") == "https://medsim-staging.jackfruitco.com"
    )


@override_settings(
    EMAIL_ENVIRONMENT_NAME="staging",
    EMAIL_BASE_URL="https://custom-staging.example.com",
)
def test_environment_helper_ignores_custom_base_url_for_explicit_other_environment():
    assert get_email_base_url(environment_hint="production") == "https://medsim.jackfruitco.com"


def test_build_standard_context_uses_environment_hint_for_links_without_request():
    context = _build_standard_context({}, environment_hint="staging")

    assert context["environment_label"] == "staging"
    assert context["is_staging"] is True
    assert context["email_base_url"] == "https://medsim-staging.jackfruitco.com"


def test_send_templated_email_task_passes_simple_serializable_payload(monkeypatch):
    captured = {}

    def fake_send_templated_email(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "apps.common.emailing.tasks.send_templated_email", fake_send_templated_email
    )

    send_templated_email_task.run(
        recipients=["clinician@example.com"],
        subject="MedSim Notice",
        template_prefix="emails/example",
        context={"foo": "bar"},
        environment_hint="staging",
    )

    assert captured["to"] == ["clinician@example.com"]
    assert captured["subject"] == "MedSim Notice"
    assert captured["template_prefix"] == "emails/example"
    assert captured["context"] == {"foo": "bar"}
    assert captured["environment_hint"] == "staging"
