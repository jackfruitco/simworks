from django.contrib.auth import urls as auth_urls
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("invitations/new", views.new_invite, name="new-invite"),
    path("invitation/new/success", views.invite_success, name="invite-success"),
    path("invitations/list/", views.list_invites, name="list-invites"),
    path("register/", views.register, name="register"),
    path("register/<slug:token>/", views.register, name="register-with-token"),
    path("profile/", views.profile, name="profile"),
]
urlpatterns += auth_urls.urlpatterns
