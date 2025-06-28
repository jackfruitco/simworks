# simai/urls.py
from django.urls import path
from simai import views

app_name = "simai"

urlpatterns = [
    path("analytics/usage/", views.usage_report, name="usage-report"),
]
