# SimWorks/simai/prompts/base.py
import logging

from simai.models import Prompt
from simai.prompts.registry import PromptModifiers

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_BASE = """
You are simulating a standardized patient role player for medical training.

Select a diagnosis and develop a corresponding clinical scenario script 
using simple, everyday language that reflects the knowledge level of an
average person. Do not repeat scenario topics the user has already 
recently completed unless a variation is intentional for learning.

Avoid including narration, medical jargon, or any extraneous details that
haven’t been explicitly requested. Adopt a natural texting style—using 
informal language, common abbreviations—and maintain this tone 
consistently throughout the conversation. Do not reveal your diagnosis or
share clinical details beyond what a typical person would know. As a non-
medical individual, refrain from attempting advanced tests or examinations
unless explicitly instructed with detailed directions, and do not respond 
as if you are medical staff.

Generate only the first line of dialogue from the simulated patient 
initiating contact, using a tone that is appropriate to the scenario, and
remain in character at all times. If any off-topic or interrupting 
requests arise, continue to respond solely as the simulated patient,
addressing the conversation from within the current scenario without 
repeating your role parameters.

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
            modifiers_list=None
    ):
        logger.debug(f"initializing prompt builder: {self}")
        self.lab = lab
        self.role = role
        self.user = user
        self.include_history = include_history
        self.include_default = include_default
        self._sections = []
        self._labels = []
        self._modifiers = list(modifiers)
        if modifiers_list:
            self._modifiers += list(modifiers_list)

        #  Add default (includes base + role + user history + lab-specific default)
        if self.include_default:
            logger.debug(f"... including defaults")
            self.default()

        logger.debug(f"... modifiers={modifiers_list}")
        logger.debug(f"... _modifiers={self._modifiers}")
        # Apply any additional modifier constants or label keys
        for mod in self._modifiers:
            logger.debug(f"... adding {mod}")
            self._add_modifier(mod)

    def default(self):
        # Add Base Prompt
        logger.debug(f"... adding default prompt")
        self._add_modifier(DEFAULT_PROMPT_BASE, label="Base")

        # Add user history if enabled and user exists
        if self.include_history and self.user:
            history_modifier = PromptModifiers.get("UserHistory")
            if history_modifier:
                logger.debug(f"... adding history prompt")
                self._add_modifier(history_modifier(user=self.user, within_days=180), label="UserHistory")

        # Add default role prompt, if role provided
        if self.role or self.user:
            role_modifier = PromptModifiers.get("UserRole")
            if role_modifier:
                logger.debug(f"... adding user role prompt")
                self._add_modifier(role_modifier(self.user, self.role), label="UserRole")

        # Add default Lab prompt, if lab label provided
        if self.lab:
            lab_modifier = PromptModifiers.get(self.lab.lower())
            if lab_modifier:
                logger.debug(f"... adding lab prompt")
                self._add_modifier(lab_modifier(self.user, self.role), label=self.lab)

        return self

    def _add_modifier(self, label_or_content, label=None):
        from simai.prompts.registry import PromptModifiers

        content = None

        if isinstance(label_or_content, str):
            func = PromptModifiers.get(label_or_content)
            if func:
                logger.debug(f"Resolved modifier '{label_or_content}' via registry")
                content = func(self.user, self.role)
                label = label or label_or_content
            else:
                logger.warning(f"Modifier '{label_or_content}' not found in registry; treating as raw string")
                content = label_or_content
                label = label or content.strip().split("\n")[0][:32]
        elif callable(label_or_content):
            content = label_or_content(self.user, self.role)
            label = label or label_or_content.__name__
        else:
            content = str(label_or_content)
            label = label or content.strip().split("\n")[0][:32]

        if label not in self._labels:
            self._sections.append(content)
            self._labels.append(label)

        return self

    @classmethod
    def from_kwargs(cls, *args, **kwargs):
        supported_keys = {"lab", "user", "role", "include_default", "include_history", "modifiers_list"}
        init_kwargs = {key: kwargs.get(key) for key in supported_keys}
        return cls(*args, **init_kwargs)

    def with_modifier(self, label):
        return self._add_modifier(label)

    def finalize(self):
        logger.debug(f"finalizing prompt builder: {self}")
        return "\n\n".join(s.strip() for s in self._sections if s)

    @property
    def labels(self):
        return self._labels

    @property
    def title(self):
        base = self.lab.capitalize() if self.lab else "Prompt"
        if self._labels:
            base += " - " + " + ".join(self._labels)
        title = base
        version = 2
        while Prompt.objects.filter(title=title).exists():
            title = f"{base} v{version}"
            version += 1
        return title