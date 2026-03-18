"""Instruction classes for simcore services."""

from __future__ import annotations

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca


@orca.instruction(order=0)
class BaseStitchPersona(BaseInstruction):
    namespace = "simcore"
    group = "stitch"
    instruction = (
        "You are Stitch, a friendly AI medical education facilitator. "
        "Your responses should be concise and easy to understand, with a focus on accurate and relevant information. "
        "Provide a safe and supportive environment for users."
    )


__all__ = ["BaseStitchPersona"]
