from datetime import UTC, datetime
import json
import uuid

from channels.generic.websocket import AsyncWebsocketConsumer

from config.logging import get_logger
from orchestrai.utils.json import json_default

logger = get_logger("notifications")


class NotificationsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            user = self.scope["user"]
            if user.is_anonymous:
                logger.warning(
                    "notifications.ws.connect_rejected",
                    path=self.scope.get("path"),
                    channel_name=self.channel_name,
                    reason="anonymous_user",
                    close_code=4001,
                )
                await self.accept()
                await self.close(code=4001)
            else:
                self.user = user
                self.group_name = f"notifications_{self.user.id}"
                await self.channel_layer.group_add(self.group_name, self.channel_name)
                await self.accept()
        except Exception:
            logger.exception(
                "notifications.ws.connect_failed",
                channel_name=self.channel_name,
                path=self.scope.get("path"),
            )
            await self.close(code=1011)

    async def disconnect(self, close_code):
        group = getattr(self, "group_name", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    # This method is called when a notification is sent to the group
    async def send_notification(self, event):
        notification = event["notification"]
        notification_type = event.get("notification_type", "info")

        await self.send(
            text_data=json.dumps(
                {
                    "notification": notification,
                    "type": notification_type,
                },
                default=json_default,
            )
        )

    async def outbox_event(self, event: dict) -> None:
        """Handle outbox events delivered by the drain worker.

        This handler receives events from the outbox drain worker and forwards
        them to connected WebSocket clients with the standardized envelope format.

        :param event: Dict containing the WebSocket envelope
        """
        envelope = event.get("event", {})

        # Validate envelope has required fields
        if not envelope.get("event_type"):
            logger.warning(
                "notifications.ws.outbox_missing_event_type",
                user_id=getattr(getattr(self, "user", None), "id", None),
                channel_name=getattr(self, "channel_name", None),
            )
            return

        # Forward the envelope to the client
        await self.send(text_data=json.dumps(envelope, default=json_default))

    @staticmethod
    def build_envelope(
        event_type: str,
        payload: dict,
        event_id: str | None = None,
        correlation_id: str | None = None,
        created_at: str | None = None,
    ) -> dict:
        """Build a standardized WebSocket event envelope.

        Args:
            event_type: Event type (e.g., 'notification.created')
            payload: Event payload data
            event_id: Unique event ID (generated if not provided)
            correlation_id: Request correlation ID for tracing
            created_at: ISO timestamp (generated if not provided)

        Returns:
            Standardized envelope dict
        """
        return {
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": event_type,
            "created_at": created_at or datetime.now(UTC).isoformat(),
            "correlation_id": correlation_id,
            "payload": payload,
        }
