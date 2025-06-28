# SimWorks/simai/prompts/utils.py
import logging
import warnings

logger = logging.getLogger(__name__)


def build_prompt(
    *modifiers_or_list,
    user=None,
    role=None,
    lab=None,
    include_default=True,
    include_history=True,
    simulation=None,
    modifiers=None,
    **kwargs,
) -> str:
    """
    Utility function to build and finalize Simulation prompts.

    :param modifiers_or_list: variadic modifiers passed positionally
    :param user: the User associated with the simulation prompt.
    :param role: the User Role associated with the simulation prompt.
    :param lab:  the Lab associated with the simulation prompt.
    :param include_default: include default prompt sections
    :param include_history: include user history
    :param modifiers: alternative to variadic positional modifiers
    :return: str: prompt string.
    """
    from simai.prompts import Prompt
    from simai.prompts.registry import PromptModifiers

    # TODO deprecated function `build_prompt`
    warnings.warn(
        "build_prompt() is deprecated. Use Prompt.build() or Prompt.abuild() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    logger.debug(f"...building prompt with modifiers={modifiers_or_list}")

    all_modifiers = (
        tuple(modifiers) if modifiers is not None else tuple(modifiers_or_list)
    )

    logger.debug(
        f"Building prompt with lab='{lab}', user={user}, role={role}, modifiers={all_modifiers}"
    )

    builder = Prompt(
        *all_modifiers,
        user=user,
        role=role,
        lab=lab,
        include_default=include_default,
        include_history=include_history,
        simulation=simulation,
        **kwargs,
    )

    prompt = builder.finalize()
    logger.debug(f"...finalized prompt:\n {prompt}")
    return prompt
