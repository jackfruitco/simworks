# Identity

## Tuple4 Model

Components resolve by tuple4 identity:

`(domain, namespace, group, name)`

Common domains:

- `services`
- `instructions`
- `codecs`
- `schemas`

## Django Resolver Behavior

The Django resolver derives identities from class names, mixins, and app context.

Defaults:

- domain: inferred from decorator/component type
- namespace/group/name: derived tokens unless explicitly provided

## Explicit Identity Hints

```python
@orca.service(namespace="chatlab", group="default", name="reply")
class GenerateReply(DjangoBaseService):
    ...
```

```python
@orca.instruction(namespace="chatlab", group="default", name="persona", order=10)
class PersonaInstruction(BaseInstruction):
    ...
```

## Determinism

- Identities are normalized.
- Collision handling depends on strict-collision settings.
- Registry checks report collisions and invalid identity entries.
