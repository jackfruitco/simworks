from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Invitation
from apps.accounts.services.invitations import audit_invitation_send_failure, audit_invitation_sent
from apps.billing.catalog import get_product
from apps.common.emailing.environment import get_email_base_url, is_staging_email_context
from apps.common.emailing.service import send_templated_email

logger = logging.getLogger(__name__)


@shared_task(bind=True, ignore_result=True)
def send_invitation_email_task(
    self,
    invitation_id: int,
    environment_hint: str | None = None,
) -> None:
    try:
        invitation = Invitation.objects.select_related("invited_by").get(pk=invitation_id)
    except Invitation.DoesNotExist:
        return

    if invitation.is_claimed or invitation.revoked_at or not invitation.email:
        return

    product_access_bundle = ""
    if invitation.product_code:
        product_access_bundle = get_product(invitation.product_code).display_name

    accept_path = reverse("accounts:invitation-accept", kwargs={"token": invitation.token})
    accept_url = f"{get_email_base_url(environment_hint=environment_hint)}{accept_path}"
    inviter = invitation.invited_by
    inviter_name = ""
    inviter_email = ""
    if inviter is not None:
        inviter_name = inviter.get_full_name().strip()
        inviter_email = inviter.email or ""

    try:
        sent = send_templated_email(
            to=[invitation.email],
            subject="You're invited to MedSim",
            template_prefix="accounts/emails/invitation",
            context={
                "invitation": invitation,
                "accept_url": accept_url,
                "inviter_name": inviter_name,
                "inviter_email": inviter_email,
                "product_access_bundle": product_access_bundle,
            },
            environment_hint=environment_hint,
        )
    except Exception as exc:
        audit_invitation_send_failure(invitation=invitation, error=exc)
        return

    if sent:
        invitation.mark_sent()
        audit_invitation_sent(invitation=invitation)


@shared_task(bind=True, ignore_result=True)
def send_staging_account_ready_email_task(
    self,
    invitation_id: int,
    environment_hint: str | None = None,
) -> None:
    if not is_staging_email_context(environment_hint=environment_hint):
        return

    try:
        invitation = Invitation.objects.get(pk=invitation_id)
    except Invitation.DoesNotExist:
        return

    if not invitation.is_claimed or not invitation.email:
        return

    with transaction.atomic():
        invitation = Invitation.objects.select_for_update().get(pk=invitation_id)
        if invitation.staging_setup_reminder_sent_at is not None:
            return

        try:
            sent = send_templated_email(
                to=[invitation.email],
                subject="Your staging account is ready — switch the iOS app to Staging",
                template_prefix="accounts/emails/staging_account_ready",
                context={},
                environment_hint=environment_hint,
            )
        except Exception:
            logger.exception(
                "Staging account ready email send failed",
                extra={"invitation_id": invitation.id},
            )
            return

        if sent:
            invitation.staging_setup_reminder_sent_at = timezone.now()
            invitation.save(update_fields=["staging_setup_reminder_sent_at"])
            logger.info(
                "Staging account ready reminder sent",
                extra={"invitation_id": invitation.id},
            )
