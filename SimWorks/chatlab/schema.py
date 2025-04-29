import graphene
from graphene_django.types import DjangoObjectType

from accounts.models import CustomUser
from chatlab.models import Message


class UserType(DjangoObjectType):
    class Meta:
        model = CustomUser
        fields = ("id", "username", "email", "first_name", "last_name")


class MessageType(DjangoObjectType):
    sender = graphene.Field(UserType)

    class Meta:
        model = Message
        fields = ("id", "simulation", "content", "sender", "timestamp", "role")


class Query(graphene.ObjectType):
    message = graphene.Field(MessageType, id=graphene.Int(required=True))
    all_message = graphene.List(MessageType)


class Mutation(graphene.ObjectType):
    pass