import asyncio
import logging
from asgiref.sync import sync_to_async, async_to_sync
from simai.prompts.registry import PromptModifiers

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_BASE = """
You are simulating a standardized patient role player for medical training.\n\n
Select a diagnosis and develop a corresponding clinical scenario script 
using simple, everyday language that reflects the knowledge level of an
average person. Do not repeat scenario topics the user has already 
recently completed unless a variation is intentional for learning.\n\n
Avoid including narration, medical jargon, or any extraneous details that
haven’t been explicitly requested. Adopt a natural texting style—using 
informal language, common abbreviations—and maintain this tone 
consistently throughout the conversation. Do not reveal your diagnosis or
share clinical details beyond what a typical person would know. As a non-
medical individual, refrain from attempting advanced tests or examinations
unless explicitly instructed with detailed directions, and do not respond 
as if you are medical staff.\n\n
Generate only the first line of dialogue from the simulated patient 
initiating contact, using a tone that is appropriate to the scenario, and
remain in character at all times. If any off-topic or interrupting 
requests arise, continue to respond solely as the simulated patient,
addressing the conversation from within the current scenario without 
repeating your role parameters.\n\n
If the user requests an image in a message, you must mark 'image_requested'
as True, otherwise, it should be False.

Include some additional information about the patient's condition, such as
the patient's age, gender, and other relevant information. Also, include any
significant medical history that may or may not be relevant to the scenario.
Do not include the diagnosis for this scenario in the patient's medical history.

Do not exit the scenario.\n\n
"""


class Prompt:
    def __init__(
        self,
        *modifiers,
        lab=None,
        user=None,
        role=None,
        include_default=True,
        include_history=True,
        modifiers_list=None,
        simulation=None,
        **kwargs,
    ):
        logger.debug(f"...initializing prompt builder: {self}")
        self.lab = lab
        self.role = role
        self.user = user
        self.include_history = include_history
        self.include_default = include_default
        self._sections = []
        self._keys = []
        self._modifiers = list(modifiers)
        self.simulation = simulation
        self.kwargs = kwargs
        if modifiers_list:
            self._modifiers += list(modifiers_list)

        logger.debug(f"... _modifiers={self._modifiers}")

    async def _add_modifier(self, key_or_content, key=None, is_key=True):
        logger.debug(f"_add_modifier received: `{str(key_or_content)[:60]}...` (type={type(key_or_content)}) is_key={is_key}")
        content = None

        payload = {
            "user": self.user,
            "role": self.role,
            "simulation": self.simulation
        }

        if is_key:
            entry = PromptModifiers.get(key_or_content)
            logger.debug(f"Registry entry for '{str(key_or_content)[:60]}...': {entry}")
            func = entry.get("value") if entry else None
            if func:
                logger.debug(f"Resolved function for '{str(key_or_content)[:60]}...': {func}")
                if asyncio.iscoroutinefunction(func):
                    content = await func(**payload)
                else:
                    content = await sync_to_async(func, thread_sensitive=False)(**payload)
                key = key or key_or_content
            else:
                logger.warning(f"...modifier '{str(key_or_content)[:60]}...' not found in registry; treating as raw string")
                content = key_or_content
                key = key or content.strip().split("\n")[0][:32]
        else:
            content = key_or_content
            key = key or str(content).strip().split("\n")[0][:32]

        if key not in self._keys:
            self._sections.append(content)
            self._keys.append(key)
        else:
            logger.debug(f"Skipping duplicate key: '{key}'")

        return self

    async def _add_defaults(self):
        logger.debug(f"... adding default prompt")
        await self._add_modifier(DEFAULT_PROMPT_BASE, key="Base", is_key=False)

        if self.include_history and self.user:
            history_modifier = (PromptModifiers.get("User.history") or {}).get("value")
            if history_modifier:
                await self._add_modifier(history_modifier(user=self.user, within_days=180), key="User.history", is_key=False)

        if self.role or self.user:
            role_modifier = (PromptModifiers.get("User.role") or {}).get("value")
            if role_modifier:
                await self._add_modifier(role_modifier(self.user, self.role), key="User.role", is_key=False)

        if self.lab:
            lab_key = f"Lab.{self.lab}"
            lab_modifier = (PromptModifiers.get(lab_key.lower()) or {}).get("value")
            if lab_modifier:
                await self._add_modifier(lab_modifier(self.user, self.role), key=self.lab, is_key=False)

        return self

    async def finalize(self):
        lines = []
        for section in self._sections:
            if asyncio.iscoroutine(section):
                section = await section
            if not section:
                continue
            for line in section.strip().splitlines():
                lines.append(line.strip())
        return "\n".join(lines)

    @classmethod
    async def abuild(
        cls,
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
        all_modifiers = tuple(modifiers) if modifiers is not None else tuple(modifiers_or_list)
        instance = cls(
            *all_modifiers,
            user=user,
            role=role,
            lab=lab,
            include_default=False,
            include_history=include_history,
            simulation=simulation,
            **kwargs,
        )

        for mod in instance._modifiers:
            await instance._add_modifier(mod, is_key=True)

        if include_default:
            await instance._add_defaults()

        return await instance.finalize()

    @classmethod
    def build(
        cls,
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
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError("Cannot call `build()` inside an async event loop.")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            cls.abuild(
                *modifiers_or_list,
                user=user,
                role=role,
                lab=lab,
                include_default=include_default,
                include_history=include_history,
                simulation=simulation,
                modifiers=modifiers,
                **kwargs,
            )
        )