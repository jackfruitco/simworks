"""ChatLab access probe endpoint (mirrors TrainerLab /access/me/)."""

from django.http import HttpRequest
from ninja import Router

from api.v1.auth import DualAuth
from api.v1.schemas.trainerlab import LabAccessOut
from apps.chatlab.access import require_lab_access as require_chatlab_access
from apps.common.ratelimit import api_rate_limit

router = Router(tags=["chatlab"], auth=DualAuth())


def _require_chatlab_access(request: HttpRequest):
    return require_chatlab_access(request.auth, request=request)


@router.get(
    "/access/me/",
    response=LabAccessOut,
    summary="Get ChatLab access for current user",
)
@api_rate_limit
def chatlab_access_me(request: HttpRequest) -> LabAccessOut:
    _require_chatlab_access(request)
    return LabAccessOut(lab_slug="chatlab")
