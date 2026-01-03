## OrchestrAI Service Lifecycle (Core)

### Pipeline
1. **Definition**
   - Services subclass `BaseService` or use the `@service` decorator (pins identity and registers in the global services registry). `shared_service` defers registration until app finalize.
   - Optional class defaults: `codec_cls`, `prompt_plan`, `prompt_engine`, `provider_name`, `response_schema`.
2. **Registration**
   - App-local: `OrchestrAI.services.register(name, obj)` (idempotent, frozen on `finalize`).
   - Global: decorators register into identity-based registries (`services`, `codecs`, `schemas`, `prompt_sections`).
   - Discovery: loader imports modules listed in `DISCOVERY_PATHS`; any shared decorators add finalize callbacks that run during `app.finalize()`.
3. **Resolution**
   - App-local lookup via `app.services.get(name)` or `current_app.services.get(name)`.
   - Identity-based resolution for codecs/schemas/prompt sections via `Identity.resolve.try_for_(kind, identity)` backed by the global registries.
4. **Preparation**
   - Context merge + `check_required_context`.
   - Prompt selection precedence: overrides (`prompt_instruction_override`/`prompt_message_override`) → explicit plan on instance/klass → prompt section registered for the service identity (wrapped in a `PromptPlan`).
   - Codec selection precedence: per-call override (`codec=`) → explicit `codec_cls` (arg or class) → `select_codecs()` (identity registry + provider/response_schema match).
   - Response schema precedence: per-call override → class default → identity registry lookup.
   - Request built from `PromptEngine` output; codec attaches schema/provider hints.
5. **Execution**
   - Resolve client (injected or registry/factory), emit request via emitter, apply retries/backoff.
   - Non-streaming: client `send_request` → codec `adecode` → emit success/failure.
   - Streaming: client `stream_request` → codec `adecode_chunk`/`afinalize_stream` → emit stream events.
6. **Finalization**
   - `ateardown` then `afinalize`/`finalize` hooks run; codec teardown is best-effort.

### Precedence & Overrides (highest → lowest)
- **Prompt content**: runtime overrides → explicit `prompt_plan` (instance/class) → identity-matched prompt section.
- **Codec**: runtime `codec=` override → explicit `codec_cls` (arg/class) → registry match via `select_codecs()`; falls back to no codec.
- **Response schema**: runtime override → class attribute → identity registry match → none.
- **Client**: injected `client` → registry-backed client → factory-built client.

### Discovery/Registration Hooks
- `DefaultLoader.autodiscover` imports configured modules; modules using `shared_service`/other shared decorators contribute finalize callbacks consumed during `app.finalize()`.

### Error Surfaces
- Missing emitter, prompt plan resolution failure, codec/schema resolution errors, and backend/client issues raise `ServiceConfigError`/`ServiceBuildRequestError` (or propagate codec errors) after retries are exhausted.
