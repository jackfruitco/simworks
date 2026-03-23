from django.utils import timezone

from apps.accounts.models import AccountMembership
from apps.accounts.services import get_personal_account_for_user
from apps.simcore.models import Simulation
from orchestrai_django.models import ServiceCall, ServiceCallAttempt


class UserDeletionService:
    @classmethod
    def delete_user(cls, user) -> None:
        personal_account = get_personal_account_for_user(user)
        simulation_ids = list(
            Simulation.objects.filter(account=personal_account).values_list("id", flat=True)
        )
        call_ids = list(
            ServiceCall.objects.filter(
                related_object_id__in=[str(i) for i in simulation_ids]
            ).values_list("id", flat=True)
        )
        if call_ids:
            ServiceCallAttempt.objects.filter(service_call_id__in=call_ids).delete()
            ServiceCall.objects.filter(id__in=call_ids).delete()
        AccountMembership.objects.filter(user=user).exclude(account=personal_account).update(
            status=AccountMembership.Status.REMOVED,
            ended_at=timezone.now(),
        )
        personal_account.delete()
        user.delete()
