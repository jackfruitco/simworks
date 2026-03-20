from orchestrai_django.models import ServiceCall, ServiceCallAttempt


class UserDeletionService:
    @classmethod
    def delete_user(cls, user) -> None:
        simulation_ids = list(user.simulation_set.values_list("id", flat=True))
        call_ids = list(
            ServiceCall.objects.filter(
                related_object_id__in=[str(i) for i in simulation_ids]
            ).values_list("id", flat=True)
        )
        if call_ids:
            ServiceCallAttempt.objects.filter(service_call_id__in=call_ids).delete()
            ServiceCall.objects.filter(id__in=call_ids).delete()
        user.delete()
