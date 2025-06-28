from django.contrib import admin

from .models import CustomUser
from .models import Invitation
from .models import RoleResource
from .models import UserRole

admin.site.register(CustomUser)
admin.site.register(Invitation)
admin.site.register(UserRole)
admin.site.register(RoleResource)
