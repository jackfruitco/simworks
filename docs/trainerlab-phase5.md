# TrainerLab Phase V: progression and portrayal

MedSim keeps clinical facts in TrainerLab. OrchestrAI supplies a structured proposal;
it does not own the clock, authorization, intervention history, or physiology writes.

## Runtime contract

- The runtime output's `vital_updates` are end-of-horizon targets. A plan captures
  their current baselines, input revision, source call, version, and a 15–120 active
  second horizon. Duplicate types, missing baselines, reversed bounds, and SpO2
  above 100% are rejected before mutation. These are structural checks, not proof
  of clinical accuracy.
- The deterministic executor interpolates bounded ranges on existing scheduler
  ticks. It never extrapolates past the horizon. Instructor-held vitals are untouched.
  Unchanged values do not create duplicate domain rows. Vital events reference the plan.
- Valid plans run without an AI call on every timer tick. At expiry the last values
  are held until a new proposal succeeds. No new realtime infrastructure is required.
- Authoritative input invalidates the prior plan and pending decisions. Pauses stop
  execution, stale tick nonces are ignored, and generation ownership checks remain.
  In-flight generation temporarily holds execution to preserve its observed revision.
- The legacy vitals-tick URL remains retry-safe but queues the same runtime planner.
  Late results from the retired independent vitals writer are rejected and audited.
- Existing catalog rules require explicit `scenario_spec.authorized_progression_rules`
  entries. Generic respiratory distress no longer autonomously becomes tension
  pneumothorax. The configured rules must match the scenario and be reviewed by
  a clinical subject-matter expert; the catalog's timing is not a validated disease model.

## Branch decisions and portrayal

New problems with an active scenario cause become durable `ScenarioDecision` records.
The same turn cannot apply that proposed branch's vital, finding, or narrative effects.
`POST /api/v1/trainerlab/simulations/{id}/decisions/{decision_id}/` accepts
`{"approved": true|false}` with `Idempotency-Key`, existing lab/account authorization,
and session locking. Changed-state decisions return 409. Approved/rejected outcomes
are auditable and repeat acknowledgments do not reapply changes. Approval never
creates an intervention. Missing or fabricated intervention IDs reject runtime output.

`presentation.progression` supplies plan status and short behavior/speech cues for
the mannequin operator or role player. `presentation.decisions` contains pending
branch cards. Cues are read-only AI text, not authoritative events. They expire with
the plan. This phase does not implement a learner screen, ambient audio, or voice entry.

iOS uses its existing durable command queue for decisions, visibly disables an
in-flight card, and refreshes canonical state after settlement. Old servers remain
compatible through optional fields. Phase V servers disable client random vital
walks; displayed numbers represent the midpoint of each server-supplied range.

## Rollout and verification

Apply migration `0005_progression_plans_and_decisions` before deploying the backend;
deploy the backend before iOS to expose the new optional presentation fields.
No existing sessions are converted or fabricated clinical facts backfilled.
Test interpolation, expiry, pause, stale ticks, held values, invalid plans, authoritative
input invalidation, branch replay/rejection/staleness, API access, and retired callbacks.

Clinical qualification remains separate from passing engineering tests: scenario-specific
trajectories, rates of change, and portrayal need reviewed medical fixtures before
claiming validated clinical realism. This implementation does not claim that qualification.
