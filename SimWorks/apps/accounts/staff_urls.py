from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("invitations/", views.invitation_dashboard_list, name="invitation-list"),
    path("invitations/new/", views.invitation_dashboard_create, name="invitation-create"),
    path(
        "invitations/<int:invitation_id>/",
        views.invitation_dashboard_detail,
        name="invitation-detail",
    ),
    path(
        "invitations/<int:invitation_id>/resend/",
        views.invitation_dashboard_resend,
        name="invitation-resend",
    ),
    path(
        "invitations/<int:invitation_id>/revoke/",
        views.invitation_dashboard_revoke,
        name="invitation-revoke",
    ),
    path("users/", views.user_dashboard_list, name="user-list"),
    path("users/<int:user_id>/", views.user_dashboard_detail, name="user-detail"),
    path("accounts/", views.account_dashboard_list, name="account-list"),
    path("accounts/<int:account_id>/", views.account_dashboard_detail, name="account-detail"),
]
