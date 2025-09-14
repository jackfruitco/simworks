import graphene
from accounts.models import CustomUser
from chatlab.models import Message
from django.shortcuts import get_object_or_404
from graphene_django.types import DjangoObjectType


class UserType(DjangoObjectType):
    class Meta:
        model = CustomUser
        fields = ("id", "username", "email", "first_name", "last_name")


class MessageType(DjangoObjectType):
    sender = graphene.Field(UserType)

    class Meta:
        model = Message
        fields = (
            "id",
            "simulation",
            "message_type",
            "media",
            "is_from_ai",
            "is_deleted",
            "content",
            "sender",
            "timestamp",
            "role",
        )


class Query(graphene.ObjectType):

    message = graphene.Field(MessageType, id=graphene.Int(required=True))

    messages = graphene.List(
        MessageType,
        ids=graphene.List(graphene.Int),
        simulation=graphene.List(graphene.Int),
        message_type=graphene.List(graphene.String),
        limit=graphene.Int(),
    )

    def resolve_message(self, info, id):
        """Return a message by id."""
        return get_object_or_404(Message, id=id)

    def resolve_messages(
        self, info, ids=None, simulation=None, message_type=None, limit=None
    ):
        """
        Return messages, optionally filtered by message IDs, simulations, and message types.

        Args:
            ids: Optional list of message IDs to include.
            simulation: Optional list of simulation IDs.
            message_type: Optional list of message types.
            limit: Max number of messages to return.

        Returns:
            QuerySet of Message objects.
        """
        qs = Message.objects.all()

        # Filter by message IDs, if provided.
        if ids:
            if not isinstance(ids, list):
                ids = [ids]
            qs = qs.filter(id__in=ids)

        # Filter by simulation IDs, if provided.
        if simulation is not None:
            qs = qs.filter(simulation__id__in=simulation)

        # Filter by message types, if provided.
        if message_type:
            qs = qs.filter(message_type__in=message_type)

        # Limit the number of messages returned, if provided.
        if limit:
            qs = qs[:limit]

        return qs


class Mutation(graphene.ObjectType):
    pass
