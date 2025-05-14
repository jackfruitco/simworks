# simai/tasks.py
from asgiref.sync import async_to_sync
from celery import shared_task

from simai.async_client import AsyncOpenAIService
from simcore.models import Simulation


@shared_task
def generate_patient_reply_image_task(simulation_id):
    """
    Celery task to asynchronously generate a patient reply image for a given simulation.

    This task retrieves the simulation object, initializes the AsyncOpenAIService,
    and uses it to generate an image representation of the patient associated
    with the simulation.

    Args:
        simulation_id: The primary key (ID) of the Simulation object for which
                      to generate the patient image.

    Returns:
        None: The task processes the image generation asynchronously and stores
              the result in the database through the service method.
    """
    simulation = Simulation.objects.get(pk=simulation_id)
    service = AsyncOpenAIService()
    async_to_sync(service.generate_patient_reply_image)(simulation=simulation)

@shared_task
def my_task():
    print('Hello from Celery!')

    return