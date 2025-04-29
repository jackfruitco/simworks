import graphene
import chatlab.schema
import accounts.schema
import simcore.schema

import graphql_jwt

class Query(
    chatlab.schema.Query,
    accounts.schema.Query,
    simcore.schema.Query,
    graphene.ObjectType,
):
    pass

class Mutation(
    chatlab.schema.Mutation,
    accounts.schema.Mutation,
    simcore.schema.Mutation,
    graphene.ObjectType,
):
    token_auth = graphql_jwt.ObtainJSONWebToken.Field()
    verify_token = graphql_jwt.Verify.Field()
    refresh_token = graphql_jwt.Refresh.Field()

schema = graphene.Schema(query=Query, mutation=Mutation)