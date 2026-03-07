"""Instruction components for class-based system prompt composition."""

from .base import BaseInstruction
from .collector import collect_instructions

__all__ = ["BaseInstruction", "collect_instructions"]
