from django.contrib import admin

from .models import (
    Account,
    AccountAuditEvent,
    AccountMembership,
    Invitation,
    Lab,
    LabMembership,
    RoleResource,
    User,
    UserRole,
)

admin.site.register(User)
admin.site.register(Invitation)
admin.site.register(UserRole)
admin.site.register(RoleResource)
admin.site.register(Lab)
admin.site.register(LabMembership)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "account_type",
        "slug",
        "owner_user",
        "parent_account",
        "is_active",
    )
    list_filter = ("account_type", "is_active", "requires_join_approval")
    search_fields = ("name", "slug", "owner_user__email")


@admin.register(AccountMembership)
class AccountMembershipAdmin(admin.ModelAdmin):
    list_display = ("account", "user", "invite_email", "role", "status", "joined_at", "ended_at")
    list_filter = ("role", "status", "account__account_type")
    search_fields = ("account__name", "user__email", "invite_email")


@admin.register(AccountAuditEvent)
class AccountAuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "account",
        "event_type",
        "actor_user",
        "target_type",
        "target_ref",
        "created_at",
    )
    list_filter = ("event_type", "target_type")
    search_fields = ("account__name", "actor_user__email", "target_ref")
