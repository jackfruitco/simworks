import logging
from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from simcore_ai.decorators.registration import BaseRegistrationDecorator
from simcore_ai.promptkit.registry import (
    PromptRegistry,
    DuplicatePromptSectionIdentityError,
)

from simcore_ai.promptkit import PromptSection

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


    def register(self, cls: type[PromptSection], identity: tuple[str, str, str], **kwargs) -> None:
        """Register the prompt section object with unique name enforcement.

        If the (origin, bucket, name) tuple already exists, this will append
        a numeric suffix to the *name* (e.g., `name-2`, `name-3`, ...) and retry,
        logging a warning on each collision. Only the `name` portion is changed.
        """
        origin, bucket, name = identity

        # Ensure the resolved identity is reflected on the class prior to registration
        setattr(cls, "origin", origin)
        setattr(cls, "bucket", bucket)
        setattr(cls, "name", name)
        # Optional convenience string form if the class uses it
        setattr(cls, "identity", f"{origin}.{bucket}.{name}")

        while True:
            try:
                PromptRegistry.register(cls)
                logger.info(
                    "Registered prompt section (%s, %s, %s) -> %s",
                    origin,
                    bucket,
                    name,
                    getattr(cls, "__name__", str(cls)),
                )
                return
            except DuplicatePromptSectionIdentityError:
                # Bump only the name portion with a numeric suffix and retry
                new_name = self._bump_suffix(name)
                logger.warning(
                    "Collision for prompt section identity (%s, %s, %s); renamed to (%s, %s, %s)",
                    origin,
                    bucket,
                    name,
                    origin,
                    bucket,
                    new_name,
                )
                name = new_name
                setattr(cls, "name", name)
                setattr(cls, "identity", f"{origin}.{bucket}.{name}")


prompt_section = PromptSectionDecorator()
