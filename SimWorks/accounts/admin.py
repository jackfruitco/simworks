from django.contrib import admin

from .models import CustomUser, Invitation, UserRole

admin.site.register(CustomUser)
admin.site.register(Invitation)
admin.site.register(UserRole)
