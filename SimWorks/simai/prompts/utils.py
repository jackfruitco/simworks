# SimWorks/simai/prompts/utils.py
import logging

logger = logging.getLogger(__name__)

def build_prompt(
    *modifiers_or_list,
    user=None,
    role=None,
    lab=None,
    include_default=True,
    include_history=True,
    modifiers=None,
) -> str:
    """
    Utility function to build and finalize Simulation prompts.

    :param modifiers_or_list: variadic modifiers passed positionally
    :param user: The User associated with the simulation prompt.
    :param role: The User Role associated with the simulation prompt.
    :param lab:  The Lab associated with the simulation prompt.
    :param include_default: include default prompt sections
    :param include_history: include user history
    :param modifiers: alternative to variadic positional modifiers
    :return: str: prompt string.
    """
    from simai.prompts import BuildPrompt
    from simai.prompts.registry import PromptModifiers

    all_modifiers = tuple(modifiers) if modifiers is not None else tuple(modifiers_or_list)

    logger.debug(f"Building prompt with lab='{lab}', user={user}, role={role}, modifiers={all_modifiers}")

    builder = BuildPrompt(
        *all_modifiers,
        user=user,
        role=role,
        lab=lab,
        include_default=include_default,
        include_history=include_history,
    )

    prompt = builder.finalize()
    logger.debug(f"...finalized prompt:\n {prompt}")
    return prompt