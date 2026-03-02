from django.contrib import admin

from .models import *


class MediaInLine(admin.TabularInline):
    model = MessageMediaLink
    fk_name = "message"
    extra = 0

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "simulation",
        "conversation",
        "sender",
        "role",
    )
    list_filter = ("simulation", "role", "sender", "conversation__conversation_type")

    fieldsets = [
        (None, {"fields": (("simulation", "conversation", "order"), ("sender", "role"))}),
        ("Contents", {"fields": ("content",)}),
    ]

    def has_change_permission(self, request, obj=None):
        return False
