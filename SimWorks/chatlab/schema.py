import strawberry
from strawberry import auto
from strawberry.django import type
from strawberry.types import Info
from django.shortcuts import get_object_or_404

from accounts.models import CustomUser
from chatlab.models import Message


@type(CustomUser)
class UserType:
    id: auto
    username: auto
    email: auto
    first_name: auto
    last_name: auto


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
class Query:
    @strawberry.field
    def message(self, info: Info, id: int) -> MessageType:
        return get_object_or_404(Message, id=id)

    @strawberry.field
    def messages(
        self,
        info: Info,
        ids: list[int] | None = None,
        simulation: list[int] | None = None,
        message_type: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MessageType]:
        qs = Message.objects.all()
        if ids:
            qs = qs.filter(id__in=ids)
        if simulation is not None:
            if isinstance(simulation, int):
                simulation = [simulation]
            qs = qs.filter(simulation__id__in=simulation)
        if message_type:
            if not isinstance(message_type, list):
                message_type = [message_type]
            qs = qs.filter(message_type__in=message_type)
        if limit:
            qs = qs[:limit]
        return list(qs)


@strawberry.type
class Mutation:
    pass

