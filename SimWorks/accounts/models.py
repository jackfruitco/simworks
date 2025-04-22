# accounts/models.py
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.shortcuts import reverse
from django.utils import timezone
from django.utils.timezone import now
from core.utils.formatters import Formatter

from simcore.models import Simulation


class CustomUser(AbstractUser):
    role = models.ForeignKey("UserRole", on_delete=models.PROTECT)

    def get_scenario_log(self, within_days=None, within_weeks=None, within_months=None):
        """
        Return a queryset of scenario data (diagnosis and chief complaint) filtered by time.
        Priority of filters: days > weeks > months.
        """
        # Prioritize the most specific time range
        if within_days is None:
            if within_weeks is not None:
                within_days = within_weeks * 7
            elif within_months is not None:
                within_days = within_months * 30  # Approximate month

        qs = Simulation.objects.filter(user=self).exclude(diagnosis__isnull=True)

        if within_days:
            cutoff = now() - timedelta(days=within_days)
            qs = qs.filter(start_timestamp__gte=cutoff)

        return qs.values("id", "start_timestamp", "diagnosis", "chief_complaint")

class UserRole(models.Model):
    title = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Role",
        default=1,
        unique=True,
    )

    def __str__(self):
        return self.title


class RoleResource(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    role = models.ForeignKey("UserRole", on_delete=models.PROTECT, related_name="resources")
    resource = models.CharField(max_length=100, blank=False, null=False, default="")

    def __str__(self):
        return self.resource

class Invitation(models.Model):
    token = models.CharField(max_length=64, unique=True, editable=False)
    email = models.EmailField(
        blank=True, null=True, help_text="Optional: email address of the invitee"
    )
    first_name = models.CharField(
        blank=True, null=True, help_text="Optional: first name of the invitee", max_length=100
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_invitations",
    )

    is_claimed = models.BooleanField(default=False)
    claimed_at = models.DateTimeField(blank=True, null=True)
    claimed_by = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitation",
    )

    def save(self, *args, **kwargs):
        if not self.token:
            # Generate a secure token; using uuid or secrets.token_urlsafe() are good choices.
            import secrets

            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=3)
        super().save(*args, **kwargs)

    def url(self, request):
        return request.build_absolute_uri(self.get_absolute_url)

    @property
    def get_absolute_url(self):
        return reverse("accounts:register-with-token", kwargs={"token": self.token})

    @property
    def is_expired(self):
        return self.expires_at and timezone.now() > self.expires_at

    def clean(self):
        if self.is_claimed and not self.claimed_at:
            raise ValidationError("Used invitation must have a claimed_at timestamp.")

    def mark_as_claimed(self, user: CustomUser = None):
        self.is_claimed = True
        self.claimed_at = timezone.now()
        self.claimed_by = user
        self.save()

    def __str__(self):
        return f"Invitation {self.token} ({'claimed' if self.is_claimed else 'unclaimed'})"
