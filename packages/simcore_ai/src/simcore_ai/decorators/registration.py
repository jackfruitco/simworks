# packages/simcore_ai/src/simcore_ai/decorators/registration.py
from __future__ import annotations

"""
DEPRECATED MODULE: simcore_ai.decorators.registration

This module used to contain the legacy registration/decorator implementation
with inline identity derivation and token stripping. The project has moved to
a resolver-centric design. Use:

    from simcore_ai.decorators.base import BaseDecorator

This shim preserves imports like:

    from simcore_ai.decorators.registration import BaseRegistrationDecorator

by aliasing to the new `BaseDecorator`. No other symbols are retained.
"""

from simcore_ai.decorators.base import BaseDecorator as BaseRegistrationDecorator

__all__ = ["BaseRegistrationDecorator"]
