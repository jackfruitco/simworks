"""
OrchestrAI Prompts Module.

Provides decorators for defining system prompts on service methods.
This replaces the external PromptSection classes with inline method decorators.

Usage:
    from orchestrai.prompts import system_prompt

    class MyService(BaseService):
        response_schema = MySchema

        @system_prompt(weight=100)  # Higher weight = earlier in prompt
        def general_instructions(self) -> str:
            return "You are a helpful assistant..."

        @system_prompt(weight=50)
        async def dynamic_context(self, ctx: RunContext) -> str:
            return f"User name: {ctx.deps['user_name']}"
"""

from orchestrai.prompts.decorators import (
    PromptMethod,
    collect_prompts,
    system_prompt,
)

__all__ = [
    "PromptMethod",
    "collect_prompts",
    "system_prompt",
]
