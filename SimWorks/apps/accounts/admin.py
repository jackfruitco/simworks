from django.contrib import admin

from .models import Invitation, RoleResource, User, UserRole

admin.site.register(User)
admin.site.register(Invitation)
admin.site.register(UserRole)
admin.site.register(RoleResource)
