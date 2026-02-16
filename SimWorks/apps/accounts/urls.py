from django.urls import path

from . import views

app_name = "invitations"
urlpatterns = [
    path("new/", views.new_invite, name="new-invite"),
    path("success/<slug:token>/", views.invite_success, name="invite-success"),
    path("list/", views.list_invites, name="list-invites"),
    # Note: Registration is now handled by allauth at /accounts/signup/?invitation=<token>
]
