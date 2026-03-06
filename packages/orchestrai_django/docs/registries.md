# Registries in orchestrai_django

> Identity-aware registries connect Services, Instructions, Codecs, and Schemas.

---

## Overview

`orchestrai_django` uses global identity registries exposed by `orchestrai.registry`:

- `services`
- `instructions`
- `codecs`
- `schemas`

Decorators register classes into these registries, and runtime resolution uses identity/domain routing.

---

## Instruction Registry

- Domain: `instructions`
- Populated by: `@orca.instruction`
- Class contract: subclass `BaseInstruction`

```python
from orchestrai.registry import instructions

all_instruction_identities = [item.identity for item in instructions.list()]
```

---

## Service Registry

- Domain: `services`
- Populated by: `@orca.service`
- Class contract: subclass `BaseService`/`DjangoBaseService`

```python
from orchestrai.registry import services

all_service_identities = [item.identity for item in services.list()]
```

---

## Registry Integrity Checks

`manage.py check` validates:

- collision state in service/codec/instruction/schema registries
- required service pairing rules (codec required, schema resolution behavior)
- instruction presence warnings for services with no instruction classes in MRO

---

## Best Practices

- Keep class names unique within a namespace/group to avoid collisions.
- Prefer explicit decorator hints when identity derivation is ambiguous.
- Load decorated modules during app startup so registries are populated before service execution.
