from django.contrib import admin

from .models import *

@admin.register(Response)
class ResponseAdmin(admin.ModelAdmin):
    list_display = ("simulation", "user", "created")
    readonly_fields = ("simulation", "user", "created")

    fieldsets = (
        ('Response Data', {"fields": ("id", "simulation", "user", "created")}),
        ('OpenAI Usage Data', {"fields": ("input_tokens", "output_tokens", "reasoning_tokens")}),
        ('Raw Output', {
            "classes": ("collapse",),
            "fields": ("raw",)
        }),
        ('Messages', {
            "classes": ("collapse",),
            "fields": ("messages",)
        }),
    )
    ordering = ("-simulation", "-created")
