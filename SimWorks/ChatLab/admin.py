from django.contrib import admin

from .models import *


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "simulation",
        "sender",
        "role",
    )
    list_filter = ("simulation", "role", "sender")

    fieldsets = [
        (None, {"fields": (("simulation", "order"), ("sender", "role"))}),
        ("Contents", {"fields": ("content",)}),
        ("OpenAI Response", {
            "classes": ("collapse",),
            "fields": ("response__raw",)
        })

    ]

    def has_change_permission(self, request, obj=None):
        return False
