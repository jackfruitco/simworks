import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension

from accounts.schema import AccountsQuery, AccountsMutation
from chatlab.schema import ChatLabQuery, ChatLabMutation
from simai.schema import SimAiQuery, SimAiMutation
from simcore.schema import SimCoreQuery, SimCoreMutation
from trainerlab.schema import TrainerLabQuery, TrainerLabMutation


@strawberry.type
class MergedQuery(
    AccountsQuery,
    ChatLabQuery,
    SimCoreQuery,
    SimAiQuery,
    TrainerLabQuery
):
    """Merged AccountsQuery root from all apps."""
    pass


@strawberry.type
class MergedMutation(
    AccountsMutation,
    ChatLabMutation,
    SimCoreMutation,
    SimAiMutation,
    TrainerLabMutation
):
    """Merged AccountsMutation root from all apps."""
    pass


schema = strawberry.Schema(
    query=MergedQuery,
    mutation=MergedMutation,
    extensions=[DjangoOptimizerExtension()],)
