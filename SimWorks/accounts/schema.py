import graphene
from accounts.models import CustomUser
from graphene_django.types import DjangoObjectType


class UserType(DjangoObjectType):
    class Meta:
        model = CustomUser
        fields = ("id", "username", "first_name", "last_name", "email", "date_joined")


class Query(graphene.ObjectType):
    me = graphene.Field(UserType)

    def resolve_me(self, info):
        user = info.context.user
        if user.is_anonymous:
            raise Exception("Not logged in!")
        return user


class Mutation(graphene.ObjectType):
    pass
