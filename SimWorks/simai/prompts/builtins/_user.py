# SimWorks/simai/prompts/builtins/_user.py
from simai.prompts.registry import modifiers
from core.utils import Formatter

def user_role_modifier(user=None, role=None):
    _role = role or getattr(user, "role", None)
    if not _role:
        return "No User Role is assigned.\n"
    return (
        f"""
        The person you are training is a {_role.title}.
        The treatment plan should reflect training at that level.
        Consider the following resources: {_role.resource_list()}.
        """
    )

def user_history_modifier(user=None, within_days=180):
    if not user:
        return ""
    get_log = getattr(user, "get_scenario_log", None)
    if not callable(get_log):
        return ""
    log = list(get_log(within_days=within_days))
    return Formatter(log).render("openai_prompt")

modifiers.register("UserRole", user_role_modifier)
modifiers.register("UserHistory", user_history_modifier)