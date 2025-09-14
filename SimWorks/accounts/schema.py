import strawberry
from strawberry import auto
from strawberry.django import type
from strawberry.types import Info

from accounts.models import CustomUser


@type(CustomUser)
class UserType:
    id: auto
    username: auto
    first_name: auto
    last_name: auto
    email: auto
    date_joined: auto


@strawberry.type
class Query:
    @strawberry.field
    def me(self, info: Info) -> UserType:
        user = info.context.user
        if user.is_anonymous:
            raise Exception("Not logged in!")
        return user


@strawberry.type
class Mutation:
    pass

