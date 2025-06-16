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

    async def _add_modifier(
            self,
            key_or_content,
            key=None,
            is_key=True,
            **kwargs,
    ) -> "Prompt":
        """
        Asynchronously adds a modifier to a prompt.

        This method processes a given modifier, either identified securely through a key
        or provided directly as content. It supports both synchronous and asynchronous
        resolution of functions and ensures that duplicate keys are not added. The resolved
        modifier content is appended to internal storage and linked with a unique key.

        :param key_or_content: Input representing either a key to resolve a modifier or the content
            of the modifier itself.
        :type key_or_content: Union[str, Callable]
        :param key: Optional explicit key to associate with the modifier. If not specified,
            it will attempt to infer or generate one.
        :type key: Optional[str]
        :param is_key: Indicates whether `key_or_content` is a key to resolve a modifier,
            or direct content. Defaults to True, treating the input as a key.
        :type is_key: bool
        :param kwargs: Additional payload parameters to be used when resolving the modifier function.
        :return: Returns a modified `Prompt` instance after adding the new modifier.
        :rtype: Prompt
        """
        logger.debug(f"_add_modifier received: `{str(key_or_content)[:60]}...` (type={type(key_or_content)}) is_key={is_key}")
        content = None

        payload = {
            "user": self.user,
            "role": self.role,
            "simulation": self.simulation,
            **kwargs,
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
        """
        Builds an instance of the class asynchronously with specified modifiers, user, role, lab, and other optional
        parameters. This method allows customization through provided modifiers or a pre-defined list. Optionally,
        default settings can be included, and a final simulation instance is generated with processed modifiers.

        :param modifiers_or_list: A variable-length list of modifiers or a single iterable containing them.
        :param user: Optional user object or identifier for whom the instance is being built.
        :param role: Optional role specification to associate with the created instance.
        :param lab: Optional lab data or object to be included in the instance creation.
        :param include_default: A boolean flag indicating whether default settings should be added (default: True).
        :param include_history: A boolean flag determining if the history should be included in the instance (default: True).
        :param simulation: An optional simulation object or data related to the instance building process.
        :param modifiers: An optional iterable of modifiers to directly use, overriding `modifiers_or_list`.
        :param kwargs: Additional keyword arguments to customize instance creation.
        :return: A string representation of the finalized instance built from the provided and default data.
        """
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
            await instance._add_modifier(mod, is_key=True, **kwargs)

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
        """
        Builds and initiates an asynchronous operation through an event loop to
        generate a result based on provided modifiers or a collection of
        parameters. The method ensures that it does not conflict with an already
        running async event loop by checking and creating a new event loop when
        necessary. Calls the asynchronous ``abuild`` method and synchronously
        returns its output.

        :param modifiers_or_list: Positional arguments representing the modifiers
            or a list of modifier items to be processed.
        :param user: Optional parameter to specify the user associated with the
            operation.
        :param role: Optional setting to determine the role context under which
            the operation is performed.
        :param lab: Optional argument specifying the lab configuration or
            environment required for the process.
        :param include_default: Boolean flag indicating whether default
            configurations should be included in the operation. Defaults to True.
        :param include_history: Boolean flag determining whether the history
            of operations should be included in the result. Defaults to True.
        :param simulation: Optional parameter to specify data for simulation
            purposes, if any.
        :param modifiers: Dictionary or data structure containing additional
            modifiers to be applied to the process.
        :param kwargs: Additional keyword arguments for extended customization
            or parameters needed in the operation.
        :return: A string containing the result produced by the asynchronous
            ``abuild`` implementation.
        """
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