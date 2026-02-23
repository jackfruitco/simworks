"""Modifier endpoints for API v1.

Provides access to simulation modifier configuration.
"""

from django.http import HttpRequest
from ninja import Query, Router

from api.v1.schemas.modifiers import ModifierGroupOut
from apps.common.ratelimit import rate_limit

router = Router(tags=["modifiers"])


@router.get(
    "/modifier-groups/",
    response=list[ModifierGroupOut],
    summary="List modifier groups",
    description="Returns available simulation modifier groups. Optionally filter by group names.",
)
@rate_limit(key="ip", limit=100, period=60, prefix="modifiers")
def list_modifier_groups(
    request: HttpRequest,
    groups: list[str] = Query(default=None, description="Filter by group names"),
) -> list[ModifierGroupOut]:
    """List available modifier groups.

    Args:
        groups: Optional list of group names to filter by.
                If not provided, returns all groups.

    Returns:
        List of modifier groups with their modifiers.
    """
    from apps.simcore.modifiers import get_modifier_groups

    modifier_groups = get_modifier_groups(groups)
    return [ModifierGroupOut(**g) for g in modifier_groups]
