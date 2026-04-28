from django.urls import path

from apps.billing import views

app_name = "billing"

urlpatterns = [
    path("", views.billing_home, name="home"),
    path("success/", views.billing_success, name="success"),
    path("return/", views.billing_return, name="return"),
]
