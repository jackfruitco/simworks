from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from core.utils import Formatter
from simcore.models import Simulation


def download_simulation_transcript(request, simulation_id):
    sim = get_object_or_404(Simulation, id=simulation_id)
    formatter = Formatter(sim.history)
    return formatter.download("chat_transcript_md", filename=f"transcript_Sim{sim.pk}")