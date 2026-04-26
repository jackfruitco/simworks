"""Modifier endpoints for API v1.

Provides access to simulation modifier configuration per lab type.
"""

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError

from api.v1.schemas.modifiers import ModifierGroupOut
from apps.common.ratelimit import rate_limit

router = Router(tags=["modifiers"])


@router.get(
    "/modifier-groups/",
    response=list[ModifierGroupOut],
    summary="List modifier groups",
    description="Returns available simulation modifier groups for the specified lab type.",
)
@rate_limit(key="ip", limit=100, period=60, prefix="modifiers")
def list_modifier_groups(
    request: HttpRequest,
    lab_type: str = Query(default="chatlab", description="Lab type identifier"),
) -> list[ModifierGroupOut]:
    """List available modifier groups for a lab.

    Args:
        lab_type: Lab identifier (e.g. "chatlab"). Defaults to "chatlab".

    Returns:
        List of modifier groups with their modifiers.

    Raises:
        400 if lab_type is unknown or its modifier catalog is invalid.
    """
    from apps.simcore.modifiers import get_modifier_groups

    try:
        groups = get_modifier_groups(lab_type)
    except ImproperlyConfigured as exc:
        raise HttpError(400, str(exc))

    return [ModifierGroupOut(**g) for g in groups]
