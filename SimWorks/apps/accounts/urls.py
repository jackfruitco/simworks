from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    # Invitation URLs
    path("invitations/new/", views.new_invite, name="new-invite"),
    path("invitations/success/<slug:token>/", views.invite_success, name="invite-success"),
    path("invitations/list/", views.list_invites, name="list-invites"),
    # Profile URLs
    path("profile/", views.profile_view, name="profile"),
    path("profile/<int:user_id>/", views.profile_view, name="profile-detail"),
    # HTMX endpoints
    path("profile/update-field/", views.update_profile_field, name="update-profile-field"),
    path("profile/upload-avatar/", views.upload_avatar, name="upload-avatar"),
    path("profile/simulation-history/", views.simulation_history_list, name="simulation-history"),
    # Note: Registration is now handled by allauth at /accounts/signup/?invitation=<token>
]
