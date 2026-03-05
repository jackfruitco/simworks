# accounts/models.py
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.timezone import now
from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFill


class CustomUserManager(UserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    objects = CustomUserManager()

    username = None
    email = models.EmailField(unique=True)
    role = models.ForeignKey("UserRole", on_delete=models.PROTECT)

    # Profile fields
    avatar = models.ImageField(
        upload_to="avatars/", blank=True, null=True, help_text="User profile photo"
    )
    avatar_thumbnail = ImageSpecField(
        source="avatar", processors=[ResizeToFill(150, 150)], format="JPEG", options={"quality": 90}
    )
    avatar_medium = ImageSpecField(
        source="avatar", processors=[ResizeToFill(300, 300)], format="JPEG", options={"quality": 90}
    )
    bio = models.TextField(blank=True, null=True, help_text="Short bio or description")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def get_scenario_log(
        self,
        within_days: float | None = None,
        within_weeks: float | None = None,
        within_months: float | None = None,
    ) -> models.QuerySet:
        from apps.simcore.models import Simulation

        # Normalize the time window (days > weeks > months)
        if within_days is None:
            if within_weeks is not None:
                within_days = within_weeks * 7
            elif within_months is not None:
                within_days = within_months * 30

        qs = (
            Simulation.objects.filter(user=self)
            .exclude(diagnosis__isnull=True)
            .order_by("-start_timestamp")
        )
        if within_days:
            cutoff = now() - timedelta(days=within_days)
            qs = qs.filter(start_timestamp__gte=cutoff)

        # Return a queryset
        return qs.values("id", "start_timestamp", "diagnosis", "chief_complaint")

    async def aget_scenario_log(
        self,
        within_days: float | None = None,
        within_weeks: float | None = None,
        within_months: float | None = None,
    ) -> list[dict]:
        """Async wrapper to get scenario log"""

        # Evaluate inside the worker thread so nothing lazy leaks to the event loop
        def _run():
            return list(
                self.get_scenario_log(
                    within_days=within_days,
                    within_weeks=within_weeks,
                    within_months=within_months,
                )
            )

        return await sync_to_async(_run)()


class UserRole(models.Model):
    title = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Role",
        default=1,
        unique=True,
    )

    @sync_to_async
    def resource_list(self, format_as="list") -> list | str:
        _list = []
        for item in RoleResource.objects.filter(role=self):
            _list.append(item.resource)

        if format_as == "list":
            return _list
        elif format_as == "str":
            return ", ".join(_list)
        else:
            raise ValidationError("Invalid format. Must be `list` or `str`.")

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
        blank=True,
        null=True,
        help_text="Optional: first name of the invitee",
        max_length=100,
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
        """Return allauth signup URL with invitation token as query parameter."""
        from django.urls import reverse as url_reverse

        return f"{url_reverse('account_signup')}?invitation={self.token}"

    @property
    def is_expired(self):
        return self.expires_at and timezone.now() > self.expires_at

    def clean(self):
        if self.is_claimed and not self.claimed_at:
            raise ValidationError("Used invitation must have a claimed_at timestamp.")

    def mark_as_claimed(self, user: "User" = None):
        self.is_claimed = True
        self.claimed_at = timezone.now()
        self.claimed_by = user
        self.save()

    def __str__(self):
        return f"Invitation {self.token} ({'claimed' if self.is_claimed else 'unclaimed'})"
