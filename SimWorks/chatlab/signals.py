# SimWorks/chatlab/signals.py
"""
ChatLab signal receivers for AI response handling.

These receivers create Message records and broadcast to WebSocket clients
when AI services complete or fail.
"""

import logging
from django.dispatch import receiver
from asgiref.sync import async_to_sync

from orchestrai_django.signals import ai_response_ready, ai_response_failed
from .models import Message
from .utils import broadcast_message

logger = logging.getLogger(__name__)


def _extract_text_from_response(response: dict) -> str:
    """
    Extract text content from an AI response payload.

    Args:
        response: Response dict from ai_response_ready signal

    Returns:
        Extracted text content, or empty string if none found
    """
    # Try to get text from common response formats
    # Format 1: {"text": "..."}
    if "text" in response:
        return str(response["text"])

    # Format 2: {"content": "..."}
    if "content" in response:
        return str(response["content"])

    # Format 3: {"output": [{"text": "..."}]}
    if "output" in response and isinstance(response["output"], list):
        for item in response["output"]:
            if isinstance(item, dict) and "text" in item:
                return str(item["text"])

    # Format 4: {"outputs": [{"text": "..."}]}
    if "outputs" in response and isinstance(response["outputs"], list):
        for item in response["outputs"]:
            if isinstance(item, dict) and "text" in item:
                return str(item["text"])

    # Format 5: {"message": "..."}
    if "message" in response:
        return str(response["message"])

    # Fallback: try to stringify the whole response
    logger.warning(
        "Could not extract text from response with keys: %s. Falling back to str(response).",
        list(response.keys())
    )
    return str(response)


@receiver(ai_response_ready)
def handle_ai_response(sender, response, context, **kwargs):
    """
    Create Message from AI response and broadcast to clients.

    This receiver handles successful AI service completions for ChatLab.
    It creates a Message record and broadcasts it via WebSocket.

    Signal payload:
        - response: dict with AI response data
        - context: dict with execution context (simulation_id, user_id, etc.)
        - domain, namespace, kind, service_name: service identity
        - correlation_id, codec_name, object_db_pk: metadata
    """
    simulation_id = context.get("simulation_id")
    if not simulation_id:
        # Not a chatlab simulation, ignore
        logger.debug(
            "Received ai_response_ready without simulation_id in context, ignoring"
        )
        return

    try:
        # Extract text from response
        text_content = _extract_text_from_response(response)

        if not text_content:
            logger.warning(
                "Empty text content extracted from AI response for simulation %s",
                simulation_id
            )
            text_content = "(No content)"

        # Create Message record
        message = Message.objects.create(
            simulation_id=simulation_id,
            content=text_content,
            role="assistant",
            is_from_ai=True,
            message_type="text",
            sender=None  # AI messages have no sender
        )

        logger.info(
            "Created Message %s from AI response for simulation %s (service: %s.%s.%s)",
            message.id,
            simulation_id,
            kwargs.get("namespace"),
            kwargs.get("kind"),
            kwargs.get("service_name")
        )

        # Broadcast via WebSocket (async function, so use async_to_sync)
        try:
            async_to_sync(broadcast_message)(message, status="completed")
            logger.debug("Broadcasted Message %s to clients", message.id)
        except Exception as broadcast_exc:
            logger.exception(
                "Failed to broadcast Message %s: %s",
                message.id,
                str(broadcast_exc)
            )

    except Exception as exc:
        logger.exception(
            "Failed to handle ai_response_ready for simulation %s: %s",
            simulation_id,
            str(exc)
        )


@receiver(ai_response_failed)
def handle_ai_failure(sender, call_id, error, context, **kwargs):
    """
    Handle AI service failures - create error message and notify user.

    This receiver handles failed AI service executions after all retries
    have been exhausted. It creates an error Message and broadcasts it.

    Signal payload:
        - call_id: ServiceCallRecord ID
        - error: Error message string
        - context: dict with execution context (simulation_id, user_id, etc.)
        - domain, namespace, kind, service_name: service identity
        - correlation_id, object_db_pk: metadata
    """
    simulation_id = context.get("simulation_id")
    if not simulation_id:
        # Not a chatlab simulation, ignore
        logger.debug(
            "Received ai_response_failed without simulation_id in context, ignoring"
        )
        return

    try:
        # Create error message for user
        error_message = Message.objects.create(
            simulation_id=simulation_id,
            content="I'm having trouble responding right now. Please try again later.",
            role="assistant",
            is_from_ai=True,
            message_type="error",
            sender=None
        )

        logger.error(
            "AI service failed for simulation %s (call_id=%s): %s. Created error Message %s.",
            simulation_id,
            call_id,
            error,
            error_message.id
        )

        # Broadcast error message to clients
        try:
            async_to_sync(broadcast_message)(error_message, status="error")
            logger.debug("Broadcasted error Message %s to clients", error_message.id)
        except Exception as broadcast_exc:
            logger.exception(
                "Failed to broadcast error Message %s: %s",
                error_message.id,
                str(broadcast_exc)
            )

    except Exception as exc:
        logger.exception(
            "Failed to handle ai_response_failed for simulation %s (call_id=%s): %s",
            simulation_id,
            call_id,
            str(exc)
        )
