"""YAML instruction loader for OrchestrAI.

Loads instruction definitions from YAML files and registers them as
``BaseInstruction`` subclasses in the instructions registry.

YAML format
-----------
.. code-block:: yaml

    namespace: chatlab   # optional; used for identity derivation
    group: patient       # optional

    instructions:
      - name: PatientSafetyBoundariesInstruction
        order: 10
        instruction: |
          ### Safety and Boundaries
          - Stay in role as the same patient for the full conversation.
          ...

      # Template variables use ${variable_name} syntax:
      - name: PatientGreeting
        order: 0
        instruction: "You are ${patient_name}, the patient."

Static instructions (no ``${...}`` placeholders) set the ``instruction``
class attribute directly, matching the interface of Python-defined classes.

Dynamic instructions (containing ``${variable}`` placeholders) override
``render_instruction()`` and substitute values from ``self.context``
(the owning service's context dict) at render time.  Missing keys render as
empty strings — no ``KeyError`` is raised.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

from orchestrai.components.instructions.base import BaseInstruction
from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN

if TYPE_CHECKING:
    pass

__all__ = ["load_yaml_instructions"]

logger = logging.getLogger(__name__)

# Matches ${variable_name} placeholders in instruction text.
_TEMPLATE_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _render_template(template: str, context: dict[str, Any]) -> str:
    """Substitute ``${variable}`` placeholders from *context*."""

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        return str(context.get(m.group(1), ""))

    return _TEMPLATE_VAR_RE.sub(_replace, template)


def _make_instruction_class(
    item: dict[str, Any],
    *,
    namespace: str | None,
    group: str | None,
) -> type[BaseInstruction]:
    """Return a new ``BaseInstruction`` subclass from a YAML item dict."""
    name: str = item["name"]
    order: int = int(item.get("order", 50))
    template: str = str(item["instruction"])

    is_dynamic = bool(_TEMPLATE_VAR_RE.search(template))

    attrs: dict[str, Any] = {
        "domain": INSTRUCTIONS_DOMAIN,
        "namespace": namespace,
        "group": group,
        "order": order,
        "abstract": False,
    }

    if is_dynamic:
        # Capture template for closure — avoids late-binding issues.
        _t = template

        async def render_instruction(self: Any) -> str:
            return _render_template(_t, self.context)

        attrs["_yaml_template"] = template
        attrs["render_instruction"] = render_instruction
    else:
        attrs["instruction"] = template

    cls = type(name, (BaseInstruction,), attrs)
    return cls


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_yaml_instructions(
    path: Path,
    *,
    app: Any | None = None,
) -> list[type[BaseInstruction]]:
    """Load and register instructions from a YAML file.

    Parameters
    ----------
    path:
        Filesystem path to the ``.yaml`` instruction file.
    app:
        The OrchestrAI application instance.  When provided, each generated
        class is registered into ``app.components.registry(INSTRUCTIONS_DOMAIN)``.
        Pass ``None`` to skip registration (useful for testing).

    Returns
    -------
    list[type[BaseInstruction]]
        The generated instruction classes, in file order.
    """
    import yaml  # deferred import — pyyaml is an optional dep

    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not data or "instructions" not in data:
        return []

    namespace: str | None = data.get("namespace")
    group: str | None = data.get("group")

    classes: list[type[BaseInstruction]] = []
    for item in data["instructions"]:
        cls = _make_instruction_class(item, namespace=namespace, group=group)
        if app is not None:
            app.components.registry(INSTRUCTIONS_DOMAIN).register(cls)
            logger.debug("Registered YAML instruction %r from %s", cls.__name__, path.name)
        classes.append(cls)

    return classes
