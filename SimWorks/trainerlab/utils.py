# trainerlab/utils.py
import logging

from django.apps import apps
from django.contrib.auth import get_user_model

from simulation.models import Simulation
from simulation.utils import generate_fake_name
from trainerlab.models import TrainerSession

User = get_user_model()
logger = logging.getLogger(__name__)


def get_app_config():
    """Lazy access to the trainerlab AppConfig; avoids touching the app registry at import time."""
    return apps.get_app_config(app_label="trainerlab")


async def create_new_simulation(
    user: User | int,
    modifiers: list | None = None,
    force: bool = False,
    request_session: bool = False,
) -> Simulation | TrainerSession:
    """Create a new Simulation and TrainerSession, and trigger a celery task."""
    sim_patient_full_name = await generate_fake_name()
    app_config = get_app_config()

    if isinstance(user, int):
        user = await User.objects.aget(id=user)

    simulation = await Simulation.abuild(
        user=user,
        lab=app_config.name,
        sim_patient_full_name=sim_patient_full_name,
        modifiers=modifiers,
    )

    session = await TrainerSession.objects.acreate(simulation=simulation)

    return simulation if not request_session else session