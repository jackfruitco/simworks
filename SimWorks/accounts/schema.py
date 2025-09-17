import strawberry
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user
from graphql import GraphQLError

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
class AccountsQuery:
    @strawberry.field
    async def me(self, info: Info) -> "UserType":
        """Return the current user."""

        request = info.context.request
        user = await sync_to_async(get_user)(request)
        if not user.is_authenticated:
            raise GraphQLError("Not logged in!")
        return user     # type: ignore


@strawberry.type
class AccountsMutation:
    pass

