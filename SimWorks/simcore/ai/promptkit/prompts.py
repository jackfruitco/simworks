from ...ai.promptkit import PromptSection, register_section
from ...models import Simulation
import logging

logger = logging.getLogger(__name__)

class CoreBaseSection(PromptSection):
    category = "core"


@register_section
class CoreDefaultSection(CoreBaseSection):
    name = "default"
    weight = 1
    instruction = "" # TODO  Core Default

