# orchestrai_django docs

`orchestrai_django` is the Django-native facade for consuming `orchestrai` in MedSim and other Django applications.

## Boundaries and responsibilities

| Layer | Responsibility |
|---|---|
| MedSim app code (`SimWorks/`) | Product features and domain workflows |
| `orchestrai_django` | Django integration, settings/persistence hooks, execution facade |
| `orchestrai` | Framework-agnostic orchestration engine |

Use this package as the primary integration boundary in Django app code.

## Core concepts

| Component | Role | Primary API |
|---|---|---|
| Service | Executable AI workflow unit | `@orca.service`, `DjangoBaseService` |
| Instruction | Prompt/system behavior fragment | `@orca.instruction`, `BaseInstruction` |
| Schema | Structured output types | `DjangoBaseOutputSchema`, `DjangoBaseOutputItem` |
| Registry | Identity-based component lookup | `orchestrai.registry` |
| Execution backend | Immediate vs queued service execution | `Service.run`, `Service.enqueue` |

## Documentation map

- [Quick start](quick-start.md)
- [Decorators](decorators.md)
- [Services](services.md)
- [Instructions](instructions.md)
- [Identity](identity.md)
- [Registries](registries.md)
- [Schemas](schemas.md)
- [Codecs](codecs.md)
- [Persistence](persistence.md)
- [Execution backends](execution_backends.md)
- [Settings](settings.md)
- [Signals](signals.md)
- [Prompt rendering](prompt_engine.md)

## Related docs

- Core engine docs: [`../../orchestrai/README.md`](../../orchestrai/README.md)
- MedSim docs index: [`../../../docs/index.md`](../../../docs/index.md)
