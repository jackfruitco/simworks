from django.template.loader import render_to_string
from django.test import RequestFactory, override_settings

from apps.accounts.adapters import InvitationAccountAdapter


@override_settings(EMAIL_STAGING_SUBJECT_PREFIX="[STAGING]")
def test_adapter_subject_not_prefixed_in_production_context():
    adapter = InvitationAccountAdapter()
    adapter._simworks_email_request = RequestFactory().get("/", HTTP_HOST="medsim.jackfruitco.com")

    subject = adapter.format_email_subject("Reset your MedSim password")

    assert not subject.startswith("[STAGING]")


@override_settings(EMAIL_STAGING_SUBJECT_PREFIX="[STAGING]")
def test_adapter_subject_prefixed_in_staging_context():
    adapter = InvitationAccountAdapter()
    adapter._simworks_email_request = RequestFactory().get(
        "/",
        HTTP_HOST="medsim-staging.jackfruitco.com",
    )

    subject = adapter.format_email_subject("Reset your MedSim password")

    assert subject.startswith("[STAGING]")


@override_settings(
    EMAIL_REPLY_TO="support@jackfruitco.com",
    EMAIL_BASE_URL="https://medsim.jackfruitco.com",
)
def test_adapter_builds_staging_context_and_reply_to():
    adapter = InvitationAccountAdapter()
    request = RequestFactory().get("/", HTTP_HOST="medsim-staging.jackfruitco.com")

    context = adapter._build_email_context(request=request, context={"request": request})

    assert context["is_staging"] is True
    assert context["environment_label"] == "staging"
    assert context["support_email"] == "support@jackfruitco.com"


@override_settings(EMAIL_REPLY_TO="support@jackfruitco.com")
def test_password_reset_templates_render_with_branding_and_staging_notice():
    html = render_to_string(
        "account/email/password_reset_key_message.html",
        {
            "product_name": "MedSim",
            "password_reset_url": "https://medsim-staging.jackfruitco.com/accounts/password/reset/key/abc/",
            "support_email": "support@jackfruitco.com",
            "is_staging": True,
        },
    )
    text = render_to_string(
        "account/email/password_reset_key_message.txt",
        {
            "product_name": "MedSim",
            "password_reset_url": "https://medsim-staging.jackfruitco.com/accounts/password/reset/key/abc/",
            "support_email": "support@jackfruitco.com",
            "is_staging": True,
        },
    )

    assert "STAGING" in html
    assert "support@jackfruitco.com" in html
    assert "MedSim" in text
    assert "STAGING NOTICE" in text


@override_settings(
    EMAIL_REPLY_TO="support@jackfruitco.com",
    EMAIL_STAGING_SUBJECT_PREFIX="[STAGING]",
)
def test_adapter_render_mail_uses_custom_templates_and_reply_to():
    adapter = InvitationAccountAdapter()
    request = RequestFactory().get("/", HTTP_HOST="medsim-staging.jackfruitco.com")
    adapter._simworks_email_request = request

    message = adapter.render_mail(
        "account/email/password_reset_key",
        "clinician@example.com",
        {
            "request": request,
            "password_reset_url": "https://medsim-staging.jackfruitco.com/accounts/password/reset/key/abc/",
        },
    )

    assert message.reply_to == ["support@jackfruitco.com"]
    assert message.subject.startswith("[STAGING]")
    assert "support@jackfruitco.com" in message.body


@override_settings(
    EMAIL_REPLY_TO="support@jackfruitco.com",
    EMAIL_BASE_URL="https://medsim.jackfruitco.com",
)
def test_adapter_context_respects_environment_hint_without_request():
    adapter = InvitationAccountAdapter()

    context = adapter._build_email_context(
        request=None,
        context={"environment_hint": "staging"},
    )

    assert context["is_staging"] is True
    assert context["environment_label"] == "staging"
    assert context["email_base_url"] == "https://medsim-staging.jackfruitco.com"
