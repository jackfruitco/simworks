"""
OrchestrAI Instructions Module.

Provides the BaseInstruction class and collect_instructions() for composing
system instructions on service classes via MRO inheritance.
"""

from .base import BaseInstruction
from .collector import collect_instructions

__all__ = ["BaseInstruction", "collect_instructions"]
