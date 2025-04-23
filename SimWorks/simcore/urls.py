# simcore/urls.py

from django.urls import path
from . import views

app_name = 'simcore'

urlpatterns = [
    path(
        "simulation/<int:simulation_id>/download/transcript/<str:format_type>",
        views.download_simulation_transcript,
        name="download_simulation_transcript"
    ),
]