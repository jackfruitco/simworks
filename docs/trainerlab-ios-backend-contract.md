# TrainerLab iOS Backend Contract Note

This note is the backend-side integration map for the iOS TrainerLab client.
The normative schema remains the generated OpenAPI document at
`docs/openapi/v1.json`.

## Route map

Map iOS service methods to these canonical backend paths:

- `listSessions` -> `GET /api/v1/trainerlab/simulations/`
- `streamSessionHubEvents` -> `GET /api/v1/trainerlab/events/stream/`
- `createSession` -> `POST /api/v1/trainerlab/simulations/`
- `getSession` -> `GET /api/v1/trainerlab/simulations/{simulation_id}/`
- `getRuntimeState` -> `GET /api/v1/trainerlab/simulations/{simulation_id}/state/`
- `streamRuntimeEvents` -> `GET /api/v1/trainerlab/simulations/{simulation_id}/events/stream/`
- `getRunSummary` -> `GET /api/v1/trainerlab/simulations/{simulation_id}/summary/`
- `startRun` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/run/start/`
- `pauseRun` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/run/pause/`
- `resumeRun` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/run/resume/`
- `stopRun` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/run/stop/`
- `injectInjury` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/events/injuries/`
- `injectIllness` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/events/illnesses/`
- `injectProblem` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/events/problems/`
- `injectIntervention` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/events/interventions/`
- `injectAssessmentFinding` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/events/assessment-findings/`
- `injectDiagnosticResult` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/events/diagnostic-results/`
- `injectResourceState` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/events/resources/`
- `injectDisposition` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/events/disposition/`
- `injectNote` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/events/notes/`
- `injectVital` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/events/vitals/`
- `listAnnotations` -> `GET /api/v1/trainerlab/simulations/{simulation_id}/annotations/`
- `createAnnotation` -> `POST /api/v1/trainerlab/simulations/{simulation_id}/annotations/`
- `getInjuryDictionary` -> `GET /api/v1/trainerlab/dictionaries/injuries/`
- `getInterventionDictionary` -> `GET /api/v1/trainerlab/dictionaries/interventions/`
- `getGuardState` -> `GET /api/v1/simulations/{simulation_id}/guard-state/`
- `sendHeartbeat` -> `POST /api/v1/simulations/{simulation_id}/heartbeat/`

Important route choice:

- Annotations are a top-level simulation subresource at
  `/api/v1/trainerlab/simulations/{simulation_id}/annotations/`.
- There is no `/events/annotations/` route in the current backend contract.

## Request and response rules

- Use the `Idempotency-Key` header for mutable TrainerLab endpoints.
- Do not send `X-Idempotency-Key`; the backend does not treat it as equivalent.
- Validation failures return the standard API `ErrorResponse` with status `422`.
- Duplicate-key conflicts and incompatible replays return `409`.
- Missing simulations or sessions return `404`.
- Initial create returns `201`; an idempotent replay of the same create returns `200`.
- Runtime screens should treat the simulation SSE stream as primary live transport and `/state/` as polling/resync fallback.
- The session hub should treat the hub SSE stream as primary live transport and `/simulations/` as polling/resync fallback.

## iOS follow-up

The backend already returns `tick_interval_seconds` in the TrainerLab session DTO.
The iOS client should treat that value as authoritative for heartbeat and vitals
timing instead of assuming a fixed interval.

This repository does not currently contain the iOS source, so any `TrainerLabAPI`,
`RunSessionStore`, or view-model updates should happen in the separate iOS
workspace while preserving the backend routes above.
