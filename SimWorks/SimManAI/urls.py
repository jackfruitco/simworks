# SimManAI/urls.py

from django.urls import path
from SimManAI import views

app_name = 'SimManAI'

urlpatterns = [
    path("analytics/usage/", views.usage_report, name="usage-report"),
]