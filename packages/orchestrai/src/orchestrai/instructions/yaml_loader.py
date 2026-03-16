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
(the owning service's context dict) at render time.

Variable substitution
---------------------
- **Required variables**: declared in ``required_variables``; validated
  before rendering.  Missing required variables raise
  :class:`~orchestrai.components.instructions.base.MissingRequiredContextError`
  immediately.
- **Non-required (optional) variables**: not declared in
  ``required_variables``; substituted with an empty string if absent.
  This is the silent-fallback policy for optional placeholders.  Document
  any placeholder that *must* be present in ``required_variables`` instead.

.. code-block:: yaml

    - name: PatientContextInstruction
      order: 20
      required_variables:
        - patient_name
        - chief_complaint
      instruction: |
        Patient: ${patient_name}
        Chief complaint: ${chief_complaint}

Identity
--------
The ``name`` of each generated class is pinned to the value from the YAML
``name`` key — no token stripping is applied.  This means refs in
``instruction_refs`` lists must use the exact YAML name, e.g.
``"chatlab.patient.PatientSafetyBoundariesInstruction"``.

Validation
----------
:func:`load_yaml_instructions` validates the YAML structure at load time.
Malformed definitions raise :class:`YAMLInstructionDefinitionError` with
the file path and a descriptive message, rather than a bare ``KeyError``.
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

__all__ = ["YAMLInstructionDefinitionError", "load_yaml_instructions"]

logger = logging.getLogger(__name__)

# Matches ${variable_name} placeholders in instruction text.
_TEMPLATE_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Keys accepted at the per-instruction item level.
_ITEM_KNOWN_KEYS = frozenset(
    {"name", "order", "instruction", "required_variables", "optional_variables"}
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class YAMLInstructionDefinitionError(ValueError):
    """Raised when a YAML instruction file contains an invalid definition.

    Attributes
    ----------
    path:
        Path to the YAML file that caused the error, if known.
    """

    def __init__(self, message: str, *, path: Path | str | None = None) -> None:
        self.path = path
        prefix = f"Invalid YAML instruction definition in {path}: " if path else ""
        super().__init__(f"{prefix}{message}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_item(item: Any, *, index: int, path: Path | str | None) -> None:
    """Validate a single instruction item dict from YAML.

    Raises :class:`YAMLInstructionDefinitionError` on the first problem found.
    """
    loc = f"instructions[{index}]"

    if not isinstance(item, dict):
        raise YAMLInstructionDefinitionError(
            f"{loc}: each instruction must be a mapping, got {type(item).__name__!r}",
            path=path,
        )

    # --- required fields ---

    name = item.get("name")
    if name is None:
        raise YAMLInstructionDefinitionError(
            f"{loc}: missing required key 'name'",
            path=path,
        )
    if not isinstance(name, str) or not name.strip():
        raise YAMLInstructionDefinitionError(
            f"{loc}: 'name' must be a non-empty string, got {name!r}",
            path=path,
        )

    instruction = item.get("instruction")
    if instruction is None:
        raise YAMLInstructionDefinitionError(
            f"{loc} ({name!r}): missing required key 'instruction'",
            path=path,
        )
    if not isinstance(instruction, str) or not instruction.strip():
        raise YAMLInstructionDefinitionError(
            f"{loc} ({name!r}): 'instruction' must be a non-empty string",
            path=path,
        )

    # --- optional fields ---

    order = item.get("order", 50)
    if not isinstance(order, int) or isinstance(order, bool):
        raise YAMLInstructionDefinitionError(
            f"{loc} ({name!r}): 'order' must be an integer, got {order!r}",
            path=path,
        )
    if not (0 <= order <= 100):
        raise YAMLInstructionDefinitionError(
            f"{loc} ({name!r}): 'order' must be between 0 and 100, got {order!r}",
            path=path,
        )

    required_vars = item.get("required_variables")
    if required_vars is not None:
        if not isinstance(required_vars, list):
            raise YAMLInstructionDefinitionError(
                f"{loc} ({name!r}): 'required_variables' must be a list[str], "
                f"got {type(required_vars).__name__!r}",
                path=path,
            )
        for i, v in enumerate(required_vars):
            if not isinstance(v, str) or not v.strip():
                raise YAMLInstructionDefinitionError(
                    f"{loc} ({name!r}): 'required_variables[{i}]' must be a "
                    f"non-empty string, got {v!r}",
                    path=path,
                )

    optional_vars = item.get("optional_variables")
    if optional_vars is not None:
        if not isinstance(optional_vars, list):
            raise YAMLInstructionDefinitionError(
                f"{loc} ({name!r}): 'optional_variables' must be a list[str], "
                f"got {type(optional_vars).__name__!r}",
                path=path,
            )
        for i, v in enumerate(optional_vars):
            if not isinstance(v, str) or not v.strip():
                raise YAMLInstructionDefinitionError(
                    f"{loc} ({name!r}): 'optional_variables[{i}]' must be a "
                    f"non-empty string, got {v!r}",
                    path=path,
                )
        # required and optional must not overlap
        req_set = set(required_vars or [])
        opt_set = set(optional_vars)
        overlap = req_set & opt_set
        if overlap:
            raise YAMLInstructionDefinitionError(
                f"{loc} ({name!r}): variables {sorted(overlap)!r} appear in both "
                "'required_variables' and 'optional_variables'",
                path=path,
            )

    # --- unknown keys (warn, not error, to allow future extensions) ---
    unknown = set(item) - _ITEM_KNOWN_KEYS
    if unknown:
        logger.warning(
            "YAML instruction %r in %s has unknown keys %r — will be ignored",
            name,
            path or "<unknown>",
            sorted(unknown),
        )


def _render_template(template: str, context: dict[str, Any]) -> str:
    """Substitute ``${variable}`` placeholders from *context*.

    Non-required (optional) variables missing from *context* are substituted
    with an empty string.  Required variables should be validated by the
    instruction before this function is called.
    """

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        return str(context.get(m.group(1), ""))

    return _TEMPLATE_VAR_RE.sub(_replace, template)


def _check_template_drift(
    template: str,
    required: tuple[str, ...],
    optional: tuple[str, ...],
    *,
    name: str,
    path: Path | str | None,
) -> None:
    """Warn at load time when template variables and declarations drift apart.

    Two conditions emit a warning:

    - A ``${variable}`` placeholder appears in the template but is not
      declared in either ``required_variables`` or ``optional_variables``
      (undeclared optional — silently renders as empty string, but the omission
      is likely unintentional).
    - A variable is declared in ``required_variables`` or ``optional_variables``
      but does not appear as a ``${variable}`` placeholder in the template
      (dead declaration).
    """
    template_vars = frozenset(_TEMPLATE_VAR_RE.findall(template))
    declared_vars = frozenset(required) | frozenset(optional)

    undeclared = template_vars - declared_vars
    if undeclared:
        logger.warning(
            "YAML instruction %r in %s: template uses ${...} variables %r that are "
            "not declared in 'required_variables' or 'optional_variables' — "
            "they will silently render as empty string",
            name,
            path or "<unknown>",
            sorted(undeclared),
        )

    dead = declared_vars - template_vars
    if dead:
        logger.warning(
            "YAML instruction %r in %s: variables %r are declared but not used in the template",
            name,
            path or "<unknown>",
            sorted(dead),
        )


def _make_instruction_class(
    item: dict[str, Any],
    *,
    namespace: str | None,
    group: str | None,
    path: Path | str | None = None,
) -> type[BaseInstruction]:
    """Return a new ``BaseInstruction`` subclass from a *pre-validated* YAML item dict."""
    name: str = item["name"]
    order: int = int(item.get("order", 50))
    template: str = str(item["instruction"])
    required: tuple[str, ...] = tuple(item.get("required_variables") or [])
    optional: tuple[str, ...] = tuple(item.get("optional_variables") or [])

    is_dynamic = bool(_TEMPLATE_VAR_RE.search(template))
    needs_validation = bool(required)

    # Warn at load time if template vars and declarations drift apart.
    _check_template_drift(template, required, optional, name=name, path=path)

    # Pin ``name`` explicitly so IdentityMixin never applies token stripping
    # (e.g. "PatientNameInstruction" must not become "PatientName").
    attrs: dict[str, Any] = {
        "domain": INSTRUCTIONS_DOMAIN,
        "namespace": namespace,
        "group": group,
        "name": name,
        "order": order,
        "abstract": False,
        "required_variables": required,
        "optional_variables": optional,
    }

    if is_dynamic:
        # Capture template in closure — avoids late-binding cell sharing.
        _t = template

        async def render_instruction(self: Any) -> str:
            self._validate_context(self.context)
            return _render_template(_t, self.context)

        attrs["_yaml_template"] = template
        attrs["render_instruction"] = render_instruction
    elif needs_validation:
        # Static text but required_variables declared: validate before returning.
        _t = template

        async def render_instruction(self: Any) -> str:  # type: ignore[no-redef]
            self._validate_context(self.context)
            return _t

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

    Raises
    ------
    YAMLInstructionDefinitionError
        If the YAML file contains an invalid instruction definition (bad types,
        missing required keys, duplicate names, etc.).
    """
    import yaml  # deferred import — pyyaml is an optional dep

    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not data or "instructions" not in data:
        return []

    if not isinstance(data["instructions"], list):
        raise YAMLInstructionDefinitionError(
            "'instructions' must be a list",
            path=path,
        )

    namespace: str | None = data.get("namespace")
    group: str | None = data.get("group")

    if namespace is not None and not isinstance(namespace, str):
        raise YAMLInstructionDefinitionError(
            f"'namespace' must be a string, got {type(namespace).__name__!r}",
            path=path,
        )
    if group is not None and not isinstance(group, str):
        raise YAMLInstructionDefinitionError(
            f"'group' must be a string, got {type(group).__name__!r}",
            path=path,
        )

    # Validate all items first so errors are reported before any registration.
    for index, item in enumerate(data["instructions"]):
        _validate_item(item, index=index, path=path)

    # Check for duplicate names within the file.
    seen_names: set[str] = set()
    for item in data["instructions"]:
        name = item["name"]
        if name in seen_names:
            raise YAMLInstructionDefinitionError(
                f"duplicate instruction name {name!r}",
                path=path,
            )
        seen_names.add(name)

    classes: list[type[BaseInstruction]] = []
    for item in data["instructions"]:
        cls = _make_instruction_class(item, namespace=namespace, group=group, path=path)
        if app is not None:
            app.components.registry(INSTRUCTIONS_DOMAIN).register(cls)
            logger.debug("Registered YAML instruction %r from %s", cls.__name__, path.name)
        classes.append(cls)

    return classes
