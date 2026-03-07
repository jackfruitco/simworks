# orchestrai_django Docs

## Architecture

| Component | Role | Primary API |
|---|---|---|
| Service | Executable unit that runs a model | `@orca.service`, `DjangoBaseService` |
| Instruction | System prompt fragment (static or dynamic) | `@orca.instruction`, `BaseInstruction` |
| Schema | Structured output models | `DjangoBaseOutputSchema`, `DjangoBaseOutputItem` |
| Registry | Identity-based component lookup | `orchestrai.registry` |

## Core Docs

- [Quick Start](quick-start.md)
- [Decorators](decorators.md)
- [Services](services.md)
- [Instructions](instructions.md)
- [Identity](identity.md)
- [Registries](registries.md)
- [Schemas](schemas.md)
- [Response processors](response processors.md)
- [Persistence](persistence.md)
- [Execution Backends](execution_backends.md)
- [Settings](settings.md)
- [Signals](signals.md)

## Migration Notes

- Prompt plans / PromptEngine / PromptSection are removed in v0.5.0.
- Use class-based instruction MRO composition instead.
