# SimWorks/simai/prompts/utils.py
import logging

logger = logging.getLogger(__name__)

def build_prompt(
    *modifiers,
    user=None,
    role=None,
    lab=None,
    include_default=True,
    include_history=True,
) -> str:
    """
    Utility function to build and finalize Simulation prompts.

    :param user: The User associated with the simulation prompt.
    :param role: The User Role associated with the simulation prompt.
    :param lab:  The Lab associated with the simulation prompt.
    :param modifiers:
    :param with_history:
    :return:
    """
    from simai.prompts import BuildPrompt

    logger.debug(f"Building prompt with lab='{lab}', user={user}, role={role}, modifiers={modifiers}")

    # Start Prompt Builder, then
    # Finalize prompt
    builder = BuildPrompt.from_kwargs(
        *modifiers,
        user=user,
        role=role,
        lab=lab,
        include_default=include_default,
        include_history=include_history,
    )
    prompt = builder.finalize()
    logger.debug(f"finalized prompt: {prompt}")
    return prompt