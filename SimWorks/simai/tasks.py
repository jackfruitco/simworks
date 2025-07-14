# simai/tasks.py
import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from chatlab.models import Message
from chatlab.utils import broadcast_event
from chatlab.utils import broadcast_message
from chatlab.utils import broadcast_patient_results
from simai.client import SimAIClient
from simcore.models import Simulation, SimulationMetadata

logger = logging.getLogger(__name__)


@shared_task(time_limit=30, soft_time_limit=20)
def generate_patient_initial(
    _simulation_id: int,
    _force: bool = False,
) -> None:
    """
    Task to asynchronously generate and broadcast initial patient messages to connected clients.

    :param _simulation_id: The unique identifier of the simulation to initialize.
    :type _simulation_id: int
    :param _force: A flag indicating whether to forcibly reinitialize the simulation.
    :type _force: bool, optional
    :return: None

    :raises Simulation.DoesNotExist: If the _simulation_id does not exist in the database.
    :raises Exception: If an error occurs during the initialization process.
    """

    async def _run(_simulation_id: int, _force: bool = False) -> None:
        """Run the task in an event loop."""
        # Coerce simulation to Simulation instance
        try:
            _simulation = await Simulation.objects.aget(id=_simulation_id)
        except Simulation.DoesNotExist:
            logger.warning(
                f"Simulation ID {_simulation_id} not found. Skipping image generation."
            )
            return

        # Generate initial message(s), and broadcast them to all connected clients
        try:
            client = SimAIClient()
            _messages: list[Message]
            _messages, _ = await client.generate_patient_initial(_simulation, False)

            for m in _messages:
                await broadcast_message(m)

        except Exception as e:
            logger.exception(
                f"Initial message generation failed for Sim#{_simulation.id}: {e}"
            )

    # Run the task in an event loop
    asyncio.run(_run(_simulation_id, _force))


@shared_task(time_limit=120, soft_time_limit=110)
def generate_patient_reply_image_task(simulation_id: int) -> None:
    async def _run(simulation_id: int) -> None:
        """
        Task to asynchronously generate a patient reply image for a given simulation.

        This task retrieves the simulation object, initializes the SimAIClient,
        and uses it to generate an image representation of the patient associated
        with the simulation.

        :param int simulation_id: The primary key (ID) of the Simulation instance.
        :return: None
        """
        try:
            simulation = await Simulation.aresolve(simulation_id)
        except Simulation.DoesNotExist:
            logger.warning(
                f"Simulation ID {simulation_id} not found. Skipping image generation."
            )
            return

        # Initiate client to generate image using Images API, then
        try:
            client = SimAIClient()
            _messages: list[Message]
            _messages, _ = await client.generate_patient_image(simulation=simulation)

            # Broadcast each message
            for m in _messages:
                await broadcast_message(m)
        except SoftTimeLimitExceeded:
            logger.warning(
                f"[generate_patient_reply_image_task] Soft time limit exceeded for Sim {simulation_id}"
            )
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            raise

    asyncio.run(_run(simulation_id))


@shared_task(time_limit=120, soft_time_limit=110)
def generate_patient_results(
    _simulation_id: int,
    _lab_orders: str | list[str] = None,
    _rad_orders: str | list[str] = None,
) -> None:
    async def _run(
        _simulation_id: int,
        _lab_orders: str | list[str] = None,
        _rad_orders: str | list[str] = None,
    ) -> None:
        """
        Generate patient results for a given simulation by interfacing with an AI client and optionally broadcasting the
        results. This function handles parsing of lab and radiology orders, manages errors during retrieval or processing,
        and enforces task time limits.

        :param _simulation_id: The unique identifier for the simulation in the database.
        :param _lab_orders: A string of comma-separated lab orders or a list of lab orders. If not provided, defaults to None.
        :param _rad_orders: A string of comma-separated radiology orders or a list of radiology orders. If not provided, defaults to None.
        :return: This function does not return a value.
        """
        try:
            simulation = await Simulation.objects.aget(id=_simulation_id)
        except Simulation.DoesNotExist:
            logger.warning(
                f"Simulation ID {_simulation_id} not found. Skipping patient result(s) generation."
            )
            raise
        except Exception as e:
            logger.error(f"Failed to retrieve simulation {_simulation_id}: {e}")
            raise

        if isinstance(_lab_orders, str):
            _lab_orders = [o.strip() for o in _lab_orders.split(",")]

        if isinstance(_rad_orders, str):
            _rad_orders = [o.strip() for o in _rad_orders.split(",")]

        try:
            client = SimAIClient()
            _results: list[SimulationMetadata]

            _, _results = await client.generate_patient_results(
                simulation=simulation, lab_orders=_lab_orders, rad_orders=_rad_orders
            )
            logger.debug(f"[generate_patient_results] Generated results: {_results}")

            # Attempt to broadcast results
            try:
                await broadcast_patient_results(_results)
            except Exception as e:
                logger.error(f"[generate_patient_results] Failed to broadcast: {e}")
        except SoftTimeLimitExceeded:
            logger.warning(
                f"[generate_patient_results] Soft time limit exceeded for Sim {_simulation_id}"
            )
        except Exception as e:
            logger.error(f"[generate_patient_results] Task failed: {e}")
            raise

    asyncio.run(_run(_simulation_id, _lab_orders, _rad_orders))


@shared_task(time_limit=30, soft_time_limit=20)
def generate_feedback(
    __simulation_id: int,
    __feedback_type: str = None,
) -> None:
    async def _run(
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
            simulation = await Simulation.objects.aget(id=__simulation_id)
        except Simulation.DoesNotExist as e:
            logger.error(f"Simulation ID {__simulation_id} not found!")
            raise
        except Exception as e:
            logger.error(
                f"Failed to retrieve simulation (provided {type(__simulation_id)} `{__simulation_id}`: {e}"
            )
            raise

        try:
            client = SimAIClient()
            _feedback: list[SimulationMetadata]
            _, _feedback = await client.generate_simulation_feedback(simulation)

            logger.debug(f"[generate_feedback] Generated feedback: {_feedback}")

            try:
                await broadcast_event(
                    __type="simulation.feedback_created",
                    __simulation=simulation,
                )
            except Exception as e:
                logger.error(f"Failed to broadcast: {e}")
        except SoftTimeLimitExceeded:
            logger.warning(
                f"[generate_patient_results] Soft time limit exceeded for Sim {__simulation_id}"
            )
        except Exception as e:
            logger.error(f"[generate_patient_results] Task failed: {e}")
            raise

    asyncio.run(_run(__simulation_id, __feedback_type))
