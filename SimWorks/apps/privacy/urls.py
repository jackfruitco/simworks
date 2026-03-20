from django.urls import path

from . import views

app_name = "privacy"

urlpatterns = [
    path("", views.privacy_policy, name="policy"),
    path("export/", views.export_user_data, name="export"),
    path("delete-account/", views.delete_account, name="delete_account"),
]
