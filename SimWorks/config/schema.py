import strawberry
from strawberry.tools import merge_types

import accounts.schema
import chatlab.schema
import simai.schema
import simcore.schema


Query = merge_types(
    "Query",
    (
        accounts.schema.Query,
        chatlab.schema.Query,
        simcore.schema.Query,
        simai.schema.Query,
    ),
)

Mutation = merge_types(
    "Mutation",
    (
        accounts.schema.Mutation,
        chatlab.schema.Mutation,
        simcore.schema.Mutation,
        simai.schema.Mutation,
    ),
)

schema = strawberry.Schema(query=Query, mutation=Mutation)

