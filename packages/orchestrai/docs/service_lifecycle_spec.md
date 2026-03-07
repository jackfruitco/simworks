## OrchestrAI Service Lifecycle (Core)

### Pipeline
1. **Definition**
   - Services subclass `BaseService` or use `@service`/`@orca.service` (pins identity and registers in services registry).
   - Instruction classes subclass `BaseInstruction` and use `@orca.instruction(order=...)`.
   - Optional class defaults: `response_schema`, `model`, `fallback_models`, `required_context_keys`.
2. **Registration**
   - App-local: `OrchestrAI.component_store.registry("services").register(...)` (idempotent, frozen on `finalize`).
   - Global: decorators register into identity domains (`services`, `instructions`, `codecs`, `schemas`).
   - Discovery: loader imports modules listed in `DISCOVERY_PATHS`; finalize callbacks registered via `connect_on_app_finalize` run during `app.finalize()`.
3. **Resolution**
   - App-local lookup via `app.component_store.registry("services").get(...)`.
   - Identity-based resolution for codecs/schemas/instructions via `Identity.resolve.try_for_(domain, identity)` backed by global registries.
4. **Preparation**
   - Context merge + `check_required_context`.
   - Instruction collection: `collect_instructions(type(service))` over service MRO.
   - Instruction ordering: `(order, class_name)` ascending.
   - Codec selection precedence: per-call override (`codec=`) -> explicit `codec_cls` (arg or class) -> `select_codecs()` (identity + provider/response_schema match).
   - Response schema precedence: per-call override -> class default -> identity registry lookup.
5. **Execution**
   - Build `Agent` from resolved model/output type.
   - Register one `agent.system_prompt(...)` callback per collected instruction (static or dynamic).
   - Run non-streaming or streaming path; decode and validate result.
6. **Finalization**
   - `teardown`/`finalize` hooks run; service call tracking finalized.

### Precedence & Overrides (highest -> lowest)
- **Instruction content**: dynamic `render_instruction` on collected instruction classes -> static `instruction` attributes.
- **Codec**: runtime `codec=` override -> explicit `codec_cls` (arg/class) -> registry match via `select_codecs()`.
- **Response schema**: runtime override -> class attribute -> identity registry match -> none.
- **Client/model**: model override in constructor -> class model -> app default model -> fallback model.

### Discovery/Registration Hooks
- `DefaultLoader.autodiscover` imports configured modules; modules can register finalize callbacks via `connect_on_app_finalize`, consumed during `app.finalize()`.

### Error Surfaces
- Missing required context, model/api key configuration errors, instruction render failures (captured defensively), codec/schema resolution errors, and backend/client issues surface as configuration/build/runtime exceptions.
