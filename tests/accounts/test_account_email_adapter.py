from allauth.account.models import EmailAddress
from allauth.core import context as allauth_context
from django.contrib.auth import get_user_model
from django.core import mail
from django.template.loader import render_to_string
from django.test import RequestFactory, override_settings
from django.urls import reverse
import pytest

from apps.accounts.adapters import InvitationAccountAdapter
from apps.accounts.models import UserRole


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


@override_settings(EMAIL_REPLY_TO="support@jackfruitco.com")
def test_email_confirmation_templates_render_with_activation_url_and_staging_notice():
    context = {
        "product_name": "MedSim",
        "activate_url": "https://medsim-staging.jackfruitco.com/accounts/confirm-email/abc/",
        "support_email": "support@jackfruitco.com",
        "is_staging": True,
    }

    html = render_to_string("account/email/email_confirmation_message.html", context)
    text = render_to_string("account/email/email_confirmation_message.txt", context)
    signup_html = render_to_string(
        "account/email/email_confirmation_signup_message.html",
        context,
    )
    signup_text = render_to_string(
        "account/email/email_confirmation_signup_message.txt",
        context,
    )

    assert context["activate_url"] in html
    assert "Verify email" in html
    assert "MedSim email verification" in text
    assert "STAGING" in html
    assert "support@jackfruitco.com" in text
    assert context["activate_url"] in signup_html
    assert "Confirm email" in signup_html
    assert "Welcome to MedSim" in signup_text
    assert "STAGING" in signup_html
    assert "STAGING NOTICE" in signup_text


@pytest.mark.django_db
@override_settings(
    ACCOUNT_ADAPTER="apps.accounts.adapters.InvitationAccountAdapter",
    ALLOWED_HOSTS=["medsim-staging.jackfruitco.com"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_REPLY_TO="support@jackfruitco.com",
    EMAIL_STAGING_SUBJECT_PREFIX="[STAGING]",
)
def test_password_reset_request_sends_branded_staging_email(client):
    user_model = get_user_model()
    role, _ = UserRole.objects.get_or_create(title="Email Test Role")
    user_model.objects.create_user(
        email="clinician@example.com",
        password="old-password",
        role=role,
    )

    response = client.post(
        reverse("account_reset_password"),
        {"email": "clinician@example.com"},
        HTTP_HOST="medsim-staging.jackfruitco.com",
    )

    assert response.status_code == 302
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.subject.startswith("[STAGING]")
    assert message.reply_to == ["support@jackfruitco.com"]
    assert "https://medsim-staging.jackfruitco.com/accounts/password/reset/key/" in message.body
    assert "support@jackfruitco.com" in message.body


@pytest.mark.django_db
@override_settings(
    ACCOUNT_ADAPTER="apps.accounts.adapters.InvitationAccountAdapter",
    ALLOWED_HOSTS=["medsim-staging.jackfruitco.com"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_REPLY_TO="support@jackfruitco.com",
    EMAIL_STAGING_SUBJECT_PREFIX="[STAGING]",
)
def test_signup_email_confirmation_send_uses_custom_template_and_staging_notice():
    user_model = get_user_model()
    role, _ = UserRole.objects.get_or_create(title="Email Test Role")
    user = user_model.objects.create_user(
        email="new-clinician@example.com",
        password="old-password",
        role=role,
    )
    email_address = EmailAddress.objects.create(
        user=user,
        email=user.email,
        primary=True,
        verified=False,
    )
    request = RequestFactory().get("/", HTTP_HOST="medsim-staging.jackfruitco.com")

    with allauth_context.request_context(request):
        email_address.send_confirmation(request, signup=True)

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.subject.startswith("[STAGING]")
    assert message.reply_to == ["support@jackfruitco.com"]
    assert "https://medsim-staging.jackfruitco.com/accounts/confirm-email/" in message.body
    assert "STAGING NOTICE" in message.body
    assert "support@jackfruitco.com" in message.body
