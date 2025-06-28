import json
import logging

logger = logging.getLogger("notifications")

from channels.generic.websocket import AsyncWebsocketConsumer


class NotificationsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            if self.scope["user"].is_anonymous:
                logger.warning(
                    "Anonymous user attempted to connect to NotificationsConsumer."
                )
                await self.close(code=4001)
            else:
                self.user = self.scope["user"]
                self.group_name = f"notifications_{self.user.id}"
                await self.channel_layer.group_add(self.group_name, self.channel_name)
                await self.accept()
        except Exception as e:
            logger.exception("Failed to connect NotificationsConsumer: %s", str(e))
            await self.close(code=1011)

    async def disconnect(self, close_code):
        group = getattr(self, "group_name", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    # This method is called when a notification is sent to the group
    async def send_notification(self, event):
        notification = event["notification"]
        notification_type = event.get("notification_type", "info")

        logger.info(
            "[Notification] Sent to user %s | Type: %s | Message: %s",
            self.user.username,
            notification_type,
            notification,
        )

        await self.send(
            text_data=json.dumps(
                {
                    "notification": notification,
                    "type": notification_type,
                }
            )
        )
