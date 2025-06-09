# simai/tasks.py
import asyncio
import logging
import warnings

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from chatlab.utils import broadcast_chat_message, broadcast_message, broadcast_patient_results, broadcast_event
from simai.client import SimAIClient
from simcore.models import Simulation, LabResult, RadResult

logger = logging.getLogger(__name__)

@shared_task(time_limit=120, soft_time_limit=110)
def generate_patient_reply_image_task(
        simulation_id: int
) -> None:
    """
    Celery task to asynchronously generate a patient reply image for a given simulation.

    This task retrieves the simulation object, initializes the SimAIClient,
    and uses it to generate an image representation of the patient associated
    with the simulation.

    :param int simulation_id: The primary key (ID) of the Simulation instance.

    :return: None
    :rtype: None
    """
    try:
        simulation = Simulation.objects.get(pk=simulation_id)
    except Simulation.DoesNotExist:
        logger.warning(f"Simulation ID {simulation_id} not found. Skipping image generation.")
        return

    async def run():
        client = SimAIClient()
        messages = await client.generate_patient_reply_image(simulation=simulation)
        for message in messages:
            await broadcast_message(message)
        return messages

    try:
        asyncio.run(run())
        return None
    except SoftTimeLimitExceeded:
        logger.warning(f"[generate_patient_reply_image_task] Soft time limit exceeded for Sim {simulation_id}")
        return f"Soft time limit exceeded for Sim {simulation_id}"
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Image generation failed: {e}")
        raise

@shared_task(time_limit=120, soft_time_limit=110)
def generate_patient_results(
        __simulation_id: int,
        __lab_orders: str | list[str] = None,
        __rad_orders: str | list[str] = None,
) -> None:
    """
    Celery task to asynchronously generate patient results for a given simulation.

    This task retrieves the simulation object, initializes the SimAIClient,
    and uses it to generate lab and/or radiology results.

    :param int __simulation_id: simulation id
    :param __lab_orders: comma-separated lab orders
    :type __lab_orders: str or list[str]
    :param __rad_orders: comma-separated radiology orders
    :type __rad_orders: str or list[str]

    :return: None: the task processes the results generation asynchronously and stores it in the database.
    :rtype: None
    """
    try:
        simulation = Simulation.objects.get(pk=__simulation_id)
    except Simulation.DoesNotExist as e:
        logger.warning(f"Simulation ID {__simulation_id} not found. Skipping patient result(s) generation.")
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve simulation (provided {type(__simulation_id)} `{__simulation_id}`: {e}")
        raise

    # Normalize input if needed
    if isinstance(__lab_orders, str):
        __lab_orders = [o.strip() for o in __lab_orders.split(",")]

    if isinstance(__rad_orders, str):
        __rad_orders = [o.strip() for o in __rad_orders.split(",")]

    async def run():
        client = SimAIClient()
        results = await client.generate_patient_results(
            simulation=simulation,
            lab_orders=__lab_orders,
            rad_orders=__rad_orders
        )
        logger.debug(f"[generate_patient_results] Generated results: {results}")

        try:
            await broadcast_patient_results(results)
        except Exception as e:
            logger.error(f"[generate_patient_results] Failed to broadcast: {e}")
        return results

    try:
        asyncio.run(run())
    except SoftTimeLimitExceeded:
        logger.warning(f"[generate_patient_results] Soft time limit exceeded for Sim {__simulation_id}")
    except Exception as e:
        logger.error(f"[generate_patient_results] Task failed: {e}")
        raise

@shared_task(time_limit=30, soft_time_limit=20)
def generate_feedback(
        __simulation_id: int,
        __feedback_type: str = None,
) -> None:
    """
    Celery task to asynchronously generate feedback a given simulation.

    This task retrieves the simulation object, initializes the SimAIClient,
    and uses it to generate requested feedback.

    :param int __simulation_id: simulation id
    :param str __feedback_type: feedback type

    :return: None: the task processes the feedback generation asynchronously and stores it in the database.
    :rtype: None
    """
    try:
        simulation = Simulation.objects.get(pk=__simulation_id)
    except Simulation.DoesNotExist as e:
        logger.error(f"Simulation ID {__simulation_id} not found!")
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve simulation (provided {type(__simulation_id)} `{__simulation_id}`: {e}")
        raise

    async def run():
        client = SimAIClient()
        feedback = await client.generate_simulation_feedback(simulation)

        logger.debug(f"[generate_feedback] Generated feedback: {feedback}")

        try:
            await broadcast_event(
                __type="feedback.created",
                __simulation=simulation,
            )
        except Exception as e:
            logger.error(f"Failed to broadcast: {e}")
        return

    try:
        asyncio.run(run())
    except SoftTimeLimitExceeded:
        logger.warning(f"[generate_patient_results] Soft time limit exceeded for Sim {__simulation_id}")
    except Exception as e:
        logger.error(f"[generate_patient_results] Task failed: {e}")
        raise