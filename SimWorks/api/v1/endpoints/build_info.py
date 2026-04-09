"""Read-only build metadata endpoint for app splash/startup display."""

from django.http import HttpRequest
from ninja import Router

from api.v1.schemas.build_info import BuildInfoOut
from apps.common.services.build_info import get_build_info_payload

router = Router(tags=["system"])


@router.get(
    "/build-info/",
    response=BuildInfoOut,
    summary="Get build metadata",
    description="Returns best-effort backend build metadata for app startup and debug screens.",
)
def build_info(request: HttpRequest) -> BuildInfoOut:
    """Expose backend artifact metadata used by the iOS splash screen."""
    return BuildInfoOut.model_validate(get_build_info_payload())
