import graphene
from django.shortcuts import get_object_or_404
from graphene_django.types import DjangoObjectType
from graphql import GraphQLField

from chatlab.models import Simulation, Message
from accounts.models import CustomUser
from chatlab.schema import MessageType
from simcore.models import SimulationMetadata


class UserType(DjangoObjectType):
    class Meta:
        model = CustomUser
        fields = ("id", "username")


class SimulationMetadataType(DjangoObjectType):
    class Meta:
        model = SimulationMetadata
        fields = [
            "id",
            "simulation",
            "attribute",
            "key",
            "value"
        ]


class SimulationType(DjangoObjectType):
    messages = graphene.List(MessageType)
    user = graphene.Field(UserType)
    metadata = graphene.List(SimulationMetadataType)

    class Meta:
        model = Simulation
        fields = (
            "id",
            "start_timestamp",
            "end_timestamp",
            "time_limit",
            "diagnosis",
            "chief_complaint"
        )

    def resolve_messages(self, info):
        return Message.objects.filter(simulation=self).order_by("-timestamp")[:10]

    def resolve_user(self, info):
        return self.user

    def resolve_metadata(self, info):
        return SimulationMetadata.objects.filter(simulation=self).order_by("-timestamp")

class Query(graphene.ObjectType):
    simulation = graphene.Field(SimulationType, id=graphene.Int(required=True))
    all_simulations = graphene.List(SimulationType)

    def resolve_simulation(self, info, id):
        return get_object_or_404(Simulation, id=id)

    def resolve_all_simulations(self, info, username=None):
        qs = Simulation.objects.all()
        if username:
            qs = qs.filter(user__username=username)
        return qs

class Mutation(graphene.ObjectType):
    pass