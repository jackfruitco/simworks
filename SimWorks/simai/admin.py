from django.contrib import admin
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe

from .models import *
from chatlab.models import Message


class MessagesInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("content", "role")
    fieldsets = [
        (None, {"fields": ("content", "role")}),
    ]

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(Response)
class ResponseAdmin(admin.ModelAdmin):
    list_display = ("__str__", "user", "created", "simulation", "type")
    list_filter = ("simulation", "user", "type")

    fieldsets = (
        ('Response Data', {"fields": ("id", "simulation", "type", "user", "created")}),
        ('OpenAI Usage Data', {"fields": ("input_tokens", "output_tokens", "reasoning_tokens")}),
        ('Raw Output', {
            "classes": ("collapse",),
            "fields": ("raw",)
        }),
        ('Messages', {
            "classes": ("collapse",),
            "fields": ("messages_list",)
        }),
    )
    ordering = ("-simulation", "-created")
    inlines = (MessagesInline,)

    def messages_list(self, obj):
        if not obj:
            return "-"
        messages = obj.messages.all()
        if not messages.exists():
            return "No messages."

        items = format_html_join(
            '\n',
            "<li><strong>{0}</strong>: {1}</li>",
            (
                (
                    msg.sender,
                    (msg.message[:100] + "…") if len(msg.message) > 100 else msg.message
                )
                for msg in messages.order_by("timestamp")
            )
        )
        return mark_safe(f"<ol>{items}</ol>")

    messages_list.short_description = "Associated Messages"

    def has_change_permission(self, request, obj=None):
        return False
