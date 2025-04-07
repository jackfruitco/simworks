from django.contrib import admin

from .models import CustomUser
from .models import Invitation

admin.site.register(CustomUser)
admin.site.register(Invitation)
