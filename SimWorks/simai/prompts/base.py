# SimWorks/simai/prompts/base.py
import logging

from simai.models import Prompt
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


class BuildPrompt:
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

        #  Add default (includes base + role + user history + lab-specific default)
        if self.include_default:
            logger.debug(f"... including defaults")
            self.default()

        logger.debug(f"... _modifiers={self._modifiers}")
        # Apply any additional modifier constants or key keys
        for mod in self._modifiers:
            logger.debug(f"... adding {mod}")
            self._add_modifier(mod, is_key=True)

    async def default(self):
        # Add Base Prompt
        logger.debug(f"... adding default prompt")
        self._add_modifier(DEFAULT_PROMPT_BASE, key="Base", is_key=False)

        # Add user history if enabled and user exists
        if self.include_history and self.user:
            history_modifier = (PromptModifiers.get("User.history") or {}).get("value")
            if history_modifier:
                logger.debug(f"... adding history prompt")
                self._add_modifier(history_modifier(user=self.user, within_days=180), key="User.history", is_key=False)

        # Add default role prompt, if role provided
        if self.role or self.user:
            role_modifier = (PromptModifiers.get("User.role") or {}).get("value")
            if role_modifier:
                logger.debug(f"... adding user role prompt")
                self._add_modifier(role_modifier(self.user, self.role), key="User.role", is_key=False)

        # Add default Lab prompt, if lab key provided
        if self.lab:
            logger.debug(f"... lab found: {self.lab} (type={type(self.lab)})")
            lab_key = f"Lab.{self.lab}"
            lab_modifier = (PromptModifiers.get(lab_key.lower()) or {}).get("value")
            if lab_modifier:
                logger.debug(f"... adding lab prompt")
                self._add_modifier(lab_modifier(self.user, self.role), key=self.lab, is_key=False)

        return self

    def _add_modifier(self, key_or_content, key=None, is_key=True):
        """
        Adds a modifier to the prompt.
        If is_key=True, it looks up the modifier in the registry.
        If is_key=False, it treats key_or_content as resolved content.
        """
        from simai.prompts.registry import PromptModifiers

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
                content = func(**payload)
                key = key or key_or_content
            else:
                logger.debug(f"No registry entry for '{str(key_or_content)[:60]}...', using as raw string.")
                logger.warning(f"...modifier '{str(key_or_content)[:60]}...' not found in registry; treating as raw string")
                content = key_or_content
                key = key or content.strip().split("\n")[0][:32]
        else:
            logger.debug(f"Skipping registry lookup; treating as resolved content")
            content = key_or_content
            key = key or str(content).strip().split("\n")[0][:32]

        logger.debug(f"Final content to add: key='{key}', content='{content[:60]}...'")

        if key not in self._keys:
            logger.debug(f"Adding new key: '{key}'")
            self._sections.append(content)
            self._keys.append(key)
            logger.debug(f"... added '{key}' as:\n '{str(content)[:60]}...'\n")
        else:
            logger.debug(f"Skipping duplicate key: '{key}'")
            logger.debug(f"... skipped duplicate key '{key}'")

        return self

    @classmethod
    def from_kwargs(cls, *args, **kwargs):
        supported_keys = {"lab", "user", "role", "include_default", "include_history", "modifiers_list"}
        init_kwargs = {key: kwargs.get(key) for key in supported_keys}
        return cls(*args, **init_kwargs)

    def with_modifier(self, key):
        return self._add_modifier(key, is_key=True)

    def finalize(self):
        logger.debug(f"finalizing prompt builder: {self}")
        lines = []
        for section in self._sections:
            if not section:
                continue
            for line in section.strip().splitlines():
                lines.append(line.strip())  # Strip leading/trailing spaces from each line
        return "\n".join(lines)

    @property
    def keys(self):
        return self._keys

    @property
    def title(self):
        base = self.lab.capitalize() if self.lab else "Prompt"
        if self._keys:
            base += " - " + " + ".join(self._keys)
        title = base
        version = 2
        while Prompt.objects.filter(title=title).exists():
            title = f"{base} v{version}"
            version += 1
        return title