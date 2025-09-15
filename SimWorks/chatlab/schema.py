import strawberry
from strawberry import auto
from strawberry.types import Info
from strawberry_django import type, field

from accounts.schema import UserType
from chatlab.models import Message


@type(Message)
class MessageType:
    id: auto
    simulation: auto
    message_type: auto
    media: auto
    is_from_ai: auto
    is_deleted: auto
    content: auto
    sender: UserType
    timestamp: auto
    role: auto


@strawberry.type
class ChatLabQuery:
    @field
    def message(self, info: Info, _id: strawberry.ID) -> MessageType:
        return Message.objects.select_related("simulation").get(id=_id)     # type: ignore

    @field
    def messages(
        self,
        info: Info,
        _ids: list[strawberry.ID] | None = None,
        _simulation_id: strawberry.ID | None = None,
        message_type: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MessageType]:
        qs = Message.objects.all()
        if _ids:
            qs = qs.filter(id__in=_ids)

        if _simulation_id is not None:
            qs = qs.filter(simulation__id__in=_simulation_id)

        if message_type:
            qs = qs.filter(message_type__in=message_type)

        if limit:
            qs = qs[:limit]
        return qs                           # type: ignore


@strawberry.type
class ChatLabMutation:
    pass

