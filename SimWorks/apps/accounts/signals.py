from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import User
from apps.accounts.services import (
    maybe_claim_pending_memberships_for_user,
    maybe_create_personal_account_for_user,
)


@receiver(post_save, sender=User)
def ensure_personal_account(sender, instance: User, created: bool, **kwargs):
    if not instance.pk:
        return
    maybe_create_personal_account_for_user(instance)
    maybe_claim_pending_memberships_for_user(instance)
