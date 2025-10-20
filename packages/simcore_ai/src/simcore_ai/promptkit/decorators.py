import logging
from collections.abc import Callable
from typing import Any

from simcore_ai.decorators.registration import BaseRegistrationDecorator
from simcore_ai.promptkit.registry import (
    PromptRegistry,
    DuplicatePromptSectionIdentityError,
)

logger = logging.getLogger(__name__)


class PromptSectionDecorator(BaseRegistrationDecorator):
    """Decorator for registering prompt sections with uniqueness enforcement.

    Ensures that registered prompt sections have unique tuple³ identities by
    appending suffixes '-2', '-3', ... to the name on collision.
    Function targets are rejected.
    """

    def wrap_function(self, func: Callable) -> Callable:
        """Reject decorating functions."""
        raise TypeError("PromptSectionDecorator cannot be used to decorate functions.")

    def register(self, obj: Any) -> Any:
        """Register the prompt section object with unique name enforcement.

        Args:
            obj: The prompt section object to register.

        Returns:
            The registered object.

        Raises:
            Any exceptions raised by PromptRegistry.register other than DuplicatePromptSectionIdentityError.
        """
        base_name = getattr(obj, "name", None)
        if not isinstance(base_name, str):
            raise ValueError("Registered object must have a string 'name' attribute.")

        suffix = 1
        while True:
            try:
                if suffix == 1:
                    registered_obj = PromptRegistry.register(obj)
                else:
                    # Create a copy or modify the name attribute with suffix
                    new_name = f"{base_name}-{suffix}"
                    # Assuming obj has a 'name' attribute that can be set
                    setattr(obj, "name", new_name)
                    registered_obj = PromptRegistry.register(obj)
                if suffix > 1:
                    logger.info(
                        "Registered prompt section with unique name '%s' after %d attempts",
                        getattr(registered_obj, "name", None),
                        suffix,
                    )
                else:
                    logger.info(
                        "Registered prompt section with name '%s'",
                        getattr(registered_obj, "name", None),
                    )
                return registered_obj
            except DuplicatePromptSectionIdentityError:
                logger.warning(
                    "Duplicate prompt section identity detected for name '%s', trying suffix '-%d'",
                    getattr(obj, "name", None),
                    suffix + 1,
                )
                suffix += 1


prompt_section = PromptSectionDecorator()
