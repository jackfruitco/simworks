# MedSim architecture

## Product vs repository naming

- **Product name:** MedSim
- **Legacy repository/internal identifiers:** `simworks`, `SimWorks`

This repository intentionally preserves legacy technical identifiers where changing them would be a refactor risk (imports, paths, environment contracts, deployment wiring).

## Architecture at a glance

### 1) Application layer (MedSim platform)

Located primarily under `SimWorks/` and top-level Django tests.

Owns:
- end-user experiences (ChatLab, TrainerLab, simulation workflows)
- Django app/domain models
- API endpoints (REST/OpenAPI)
- web templates and UI interactions

Does **not** own:
- provider/backend-agnostic orchestration primitives (those live in `orchestrai`)

### 2) Orchestration engine layer (`orchestrai`)

Located under `packages/orchestrai/`.

Owns:
- provider/client abstractions
- service and schema primitives
- registries and discovery lifecycle
- shared orchestration settings + codecs/tooling primitives

Does **not** own:
- Django persistence concerns
- Django app wiring, model coupling, or framework-specific runtime behavior

### 3) Django integration layer (`orchestrai_django`)

Located under `packages/orchestrai_django/`.

Owns:
- Django-facing decorators and execution helpers
- settings/persistence/model integration with Django projects
- bridge APIs that keep app code stable while using `orchestrai`

Does **not** own:
- product-level business workflows in MedSim apps
- provider-agnostic core orchestration definitions that belong in `orchestrai`

## Integration guidance

- Use **`orchestrai` directly** when building framework-agnostic orchestration primitives.
- Use **`orchestrai_django`** when implementing MedSim app features in Django.
- Keep application code at the Django facade boundary when possible so low-level `orchestrai` internals do not leak into feature code.
