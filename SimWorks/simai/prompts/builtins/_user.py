# SimWorks/simai/prompts/builtins/_user.py
"""PromptModifiers that modify the user information for a simulation."""
from asgiref.sync import sync_to_async

from simai.prompts.registry import register_modifier
from core.utils import Formatter

@register_modifier("User.role")
def user_role_modifier(user=None, role=None, **kwargs):
    """Returns string for a(n) User Role modifier."""
    _role = role or getattr(user, "role", None)
    if not _role:
        return "No User Role is assigned.\n"
    return (
        f"""
        The person you are training is a {_role.title}. \
        The treatment plan should reflect training at that level. \
        Consider the following resources: {_role.resource_list()}.
        """
    )


@register_modifier("User.history")
async def user_history_modifier(user=None, within_days=180, **kwargs):
    """Returns string for a(n) User History modifier."""
    if not user:
        return ""

    get_log = getattr(user, "get_scenario_log", None)
    if not callable(get_log):
        return ""

    log = await sync_to_async(lambda: list(get_log(within_days=within_days)))()

    return Formatter(log).render("openai_prompt")