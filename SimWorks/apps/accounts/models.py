# accounts/models.py
from datetime import timedelta
import uuid

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
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
    active_account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_for_users",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def get_scenario_log(
        self,
        within_days: float | None = None,
        within_weeks: float | None = None,
        within_months: float | None = None,
    ) -> models.QuerySet:
        from apps.accounts.services.accounts import get_personal_account_for_user
        from apps.simcore.models import Simulation

        # Normalize the time window (days > weeks > months)
        if within_days is None:
            if within_weeks is not None:
                within_days = within_weeks * 7
            elif within_months is not None:
                within_days = within_months * 30

        personal_account = get_personal_account_for_user(self)
        qs = (
            Simulation.objects.filter(
                Q(account=personal_account) | Q(account__isnull=True, user=self)
            )
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


class Account(models.Model):
    class AccountType(models.TextChoices):
        PERSONAL = "personal", "Personal"
        ORGANIZATION = "organization", "Organization"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True)
    account_type = models.CharField(
        max_length=32,
        choices=AccountType.choices,
        default=AccountType.PERSONAL,
    )
    parent_account = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_accounts",
    )
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_accounts",
    )
    is_active = models.BooleanField(default=True)
    requires_join_approval = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["owner_user"],
                condition=Q(
                    owner_user__isnull=False,
                    account_type="personal",
                ),
                name="uniq_personal_account_owner_user",
            ),
        ]
        indexes = [
            models.Index(fields=["account_type", "is_active"], name="idx_account_type_active"),
            models.Index(fields=["owner_user"], name="idx_account_owner_user"),
        ]

    def clean(self):
        super().clean()
        if self.account_type == self.AccountType.PERSONAL:
            if self.parent_account_id is not None:
                raise ValidationError("Personal accounts cannot have a parent account.")
            if self.owner_user_id is None:
                raise ValidationError("Personal accounts must have an owner user.")

    @property
    def is_personal(self) -> bool:
        return self.account_type == self.AccountType.PERSONAL

    @property
    def is_organization(self) -> bool:
        return self.account_type == self.AccountType.ORGANIZATION

    def __str__(self):
        return self.name


class AccountMembership(models.Model):
    class Role(models.TextChoices):
        BILLING_ADMIN = "billing_admin", "Billing Admin"
        ORG_ADMIN = "org_admin", "Org Admin"
        INSTRUCTOR = "instructor", "Instructor"
        GENERAL_USER = "general_user", "General User"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PENDING = "pending", "Pending"
        SUSPENDED = "suspended", "Suspended"
        REMOVED = "removed", "Removed"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="account_memberships",
    )
    invite_email = models.EmailField(blank=True, default="")
    role = models.CharField(
        max_length=32,
        choices=Role.choices,
        default=Role.GENERAL_USER,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invited_account_memberships",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_account_memberships",
    )
    joined_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("account_id", "invite_email", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["account", "user"],
                condition=Q(user__isnull=False, ended_at__isnull=True),
                name="uniq_open_account_membership_user",
            ),
            models.UniqueConstraint(
                fields=["account", "invite_email"],
                condition=Q(invite_email__gt="", ended_at__isnull=True),
                name="uniq_open_account_membership_email",
            ),
        ]
        indexes = [
            models.Index(
                fields=["account", "status", "role"],
                name="idx_account_membership_acl",
            ),
            models.Index(fields=["user", "status"], name="idx_account_membership_user_status"),
            models.Index(
                fields=["invite_email", "status"],
                name="idx_account_membership_invite_email",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.user_id and not self.invite_email:
            raise ValidationError("Membership requires a linked user or invite_email.")

    @property
    def is_active_membership(self) -> bool:
        return self.status == self.Status.ACTIVE and self.ended_at is None

    def __str__(self):
        identity = self.user_id or self.invite_email or "unknown"
        return f"{self.account_id}:{identity}:{self.role}"


class AccountAuditEvent(models.Model):
    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.CASCADE,
        related_name="audit_events",
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="account_audit_events",
    )
    event_type = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100, blank=True, default="")
    target_ref = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["account", "created_at"], name="idx_account_audit_account"),
            models.Index(fields=["event_type", "created_at"], name="idx_account_audit_type"),
        ]

    def __str__(self):
        return f"{self.account_id}:{self.event_type}"


class Lab(models.Model):
    """Lab entitlement target (e.g., chatlab, trainerlab)."""

    slug = models.SlugField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("slug",)

    def __str__(self):
        return self.display_name


class LabMembership(models.Model):
    """User access grant for a specific lab."""

    class AccessLevel(models.TextChoices):
        VIEWER = "viewer", "Viewer"
        INSTRUCTOR = "instructor", "Instructor"
        ADMIN = "admin", "Admin"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lab_memberships",
    )
    lab = models.ForeignKey(
        "accounts.Lab",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    access_level = models.CharField(
        max_length=20,
        choices=AccessLevel.choices,
        default=AccessLevel.INSTRUCTOR,
    )
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_lab_memberships",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "lab"],
                name="uniq_lab_membership_user_lab",
            ),
        ]
        indexes = [
            models.Index(
                fields=["lab", "is_active", "access_level"], name="idx_lab_membership_acl"
            ),
            models.Index(fields=["user", "is_active"], name="idx_lab_membership_user"),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.lab.slug}:{self.access_level}"


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
