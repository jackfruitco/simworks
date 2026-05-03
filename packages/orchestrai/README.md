# orchestrai

`orchestrai` is the provider-agnostic orchestration engine used by the MedSim platform.

It provides reusable primitives for building structured AI workflows without coupling to Django or MedSim application code.

## What problem it solves

`orchestrai` standardizes how projects:
- configure providers/clients,
- register services/schemas/tools,
- run explicit lifecycle bootstrapping (`configure → setup → discover → finalize`, or use `start()` as a shortcut for `discover + finalize`),
- and keep orchestration behavior consistent across environments.

## What it owns

- application lifecycle + settings loading
- provider and client registries
- service and schema registration primitives
- discovery/finalization hooks
- codecs/tooling primitives shared across integrations

## What it does not own

- Django models/persistence
- Django app settings layout
- product feature workflows (ChatLab, TrainerLab, etc.)

Those concerns belong to MedSim app code and `orchestrai_django`.

## Relationship to `orchestrai_django`

- Use **`orchestrai`** for framework-agnostic orchestration logic.
- Use **`orchestrai_django`** when integrating orchestration into Django apps.

In MedSim, app code should usually consume the Django-facing APIs from `orchestrai_django`, while the lower-level orchestration contracts stay in `orchestrai`.

## Core concepts

- **Provider**: model/backend adapter implementation (for example OpenAI-backed provider).
- **Client**: configured access point that selects providers and runtime behavior.
- **Service**: executable orchestration unit.
- **Schema**: structured output contract.
- **Registry**: validated lookup store for registered components.
- **Lifecycle**: explicit setup/discovery/finalization steps to avoid import-time side effects. `start()` is a shortcut that calls `discover()` + `finalize()` and prints a component summary.

## Minimal usage

```python
from orchestrai import OrchestrAI

app = OrchestrAI()
app.configure(
    {
        "CLIENT": "default",
        "CLIENTS": {"default": {"name": "default", "api_key": "token"}},
        "PROVIDERS": {"default": {"backend": "openai", "model": "gpt-4o-mini"}},
        # Override DISCOVERY_PATHS to add custom modules, or set to () to disable autodiscovery.
        "DISCOVERY_PATHS": ["my_project.services"],
    }
)
app.setup()
app.start()  # shortcut for discover() + finalize(); prints a component summary
```

## Stability notes

- Lifecycle APIs and registry patterns are core/stable surfaces.
- Discovery conventions and some integration helper patterns may evolve; check package docs when upgrading.

## Documentation

- Quick start: [`docs/quick_start.md`](docs/quick_start.md)
- Full guide: [`docs/full_documentation.md`](docs/full_documentation.md)
- Service lifecycle reference: [`docs/service_lifecycle_spec.md`](docs/service_lifecycle_spec.md)
- MedSim platform docs: [`../../docs/index.md`](../../docs/index.md)
- Django integration package: [`../orchestrai_django/README.md`](../orchestrai_django/README.md)
