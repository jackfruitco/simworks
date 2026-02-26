# simcore/orca/prompts/__init__.py
"""
Simulation prompts module.

NOTE: Prompt sections have been migrated to @system_prompt decorated methods
on service classes. See simcore/orca/services/feedback.py for the new pattern.

The scenarios submodule remains for any scenario-specific definitions.
"""

# Sections removed - prompts are now defined on service classes via @system_prompt
from .scenarios import *

__all__ = []
