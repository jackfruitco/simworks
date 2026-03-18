# AI orchestration and prompting guidance

## Separation of concerns

- Keep orchestration primitives in `orchestrai`.
- Keep Django runtime integration in `orchestrai_django`.
- Keep product/domain prompt behavior in app-local code under `SimWorks/.../orca/`.

## Registration and lifecycle

- Prefer explicit lifecycle flow (`configure`, `setup`, `discover`, `finalize`, `start`).
- Avoid import-time execution that mutates global registries unexpectedly.
- Validate identities/keys before registry insertion; fail clearly on collisions.

## Prompt/schema discipline

- Instruction and schema docs must reflect current package APIs.
- Keep terminology consistent: provider vs service vs client.
- Do not blur framework internals into app-level feature documentation.

## Safety and correctness

- Preserve auditability for AI requests/responses and downstream persistence hooks.
- Keep async/sync execution pathways behaviorally aligned where both are supported.
