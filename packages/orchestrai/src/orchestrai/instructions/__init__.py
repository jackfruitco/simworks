"""OrchestrAI instruction system — hybrid YAML + Python architecture.

Overview
--------
Instructions are prompt fragments that compose together to build the full
system prompt delivered to an LLM.  They are collected per-service, sorted
by ``order``, and rendered to text before each service call.

Architecture: hybrid YAML + Python
-----------------------------------
**YAML instructions** are the primary format for static and declarative
dynamic content:

- Static text — no substitution needed.
- Declarative variable substitution via ``${variable}`` placeholders.
- ``required_variables`` declarations for fail-fast context validation.
- Authored and edited without Python knowledge.
- Stored at ``{app}/orca/instructions/*.yaml``.

**Python instructions** are the right tool for dynamic computation:

- DB queries (patient records, simulation history, scenario context).
- Service calls or aggregated history.
- Complex branching or role-sensitive logic.
- Custom formatting of computed values.

When a Python instruction needs to pass rich data to a YAML placeholder, the
pattern is: **Python computes** → stores in context → **YAML renders**:

.. code-block:: python

    # Python: build the value
    class RecentHistoryInstruction(BaseInstruction):
        async def render_instruction(self) -> str:
            history = await fetch_recent_cases(...)
            return "Recent cases:\\n" + format_as_bullet_list(history)

.. code-block:: yaml

    # YAML: static policy text that references the computed value
    - name: AvoidRepeatCasesInstruction
      required_variables:
        - recent_history_summary
      instruction: |
        ${recent_history_summary}
        Do not repeat any of the above cases.

Composition: instruction_refs
-------------------------------
Services declare which instructions they use via the ``instruction_refs``
class attribute:

.. code-block:: python

    class GenerateInitialResponse(DjangoBaseService):
        instruction_refs = [
            "chatlab.patient.PatientNameInstruction",  # Python
            "common.shared.CharacterConsistencyInstruction",  # YAML
            "chatlab.patient.PatientSchemaContractInstruction",  # YAML
        ]

**Ref format**: ``"namespace.group.ClassName"`` (3-part, preferred) or
``"domain.namespace.group.ClassName"`` (4-part).  Bare class names are
deprecated and emit a ``DeprecationWarning``.

**Ordering**: the list declares *which* instructions are included, not their
order.  Final order is determined by each instruction's ``order`` attribute
(lower = rendered first), then ``__name__`` for tie-breaking.  This keeps
ordering metadata co-located with each instruction definition, not scattered
across service files.

Context and variable validation
---------------------------------
At render time each instruction has access to the service's ``context`` dict
via ``self.context``.

YAML instructions declare required variables explicitly:

.. code-block:: yaml

    required_variables:
      - patient_name
      - chief_complaint

If any required variable is absent, ``render_instruction()`` raises
:class:`~orchestrai.components.instructions.base.MissingRequiredContextError`
immediately — no silent empty-string fallback.

Non-required (optional) variables missing from context silently render as
empty string.  Use ``required_variables`` for anything that must be present.

Identity and naming
---------------------
Instruction identities follow the pattern::

    domain.namespace.group.ClassName

where ``domain`` is always ``"instructions"``.

Class names are **pinned** — neither the ``@orca.instruction`` decorator nor
the YAML loader applies token stripping.  ``PatientNameInstruction`` remains
``PatientNameInstruction`` in the registry, not ``PatientName``.  This means
refs must use the exact class name as it appears in Python or YAML source.

Exports
-------
"""

from orchestrai.components.instructions import BaseInstruction, collect_instructions
from orchestrai.components.instructions.base import MissingRequiredContextError
from orchestrai.instructions.yaml_loader import (
    YAMLInstructionDefinitionError,
    load_yaml_instructions,
)

__all__ = [
    "BaseInstruction",
    "MissingRequiredContextError",
    "YAMLInstructionDefinitionError",
    "collect_instructions",
    "load_yaml_instructions",
]
