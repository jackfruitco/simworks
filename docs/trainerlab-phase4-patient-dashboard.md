# TrainerLab Phase IV: patient-first dashboard

`GET /api/v1/trainerlab/simulations/{id}/state/` now includes a compact
`presentation` projection for the live instructor dashboard. It is derived
deterministically from the authoritative scenario and runtime snapshots; it
does not invoke AI or create new clinical facts.

The projection contains the current patient summary, concise instructor cue,
up to three upcoming changes and monitoring targets, critical attention items,
held vital types, and capabilities derived from the server-side session state.
Clients should use those capabilities to present controls, while the mutation
endpoints remain authoritative and continue to reject invalid transitions.

The full scenario snapshot and event timeline remain available for detail and
recovery views. They are not intended to dominate the primary live-simulation
surface. Existing clients may ignore `presentation`; the iOS client also
retains local fallbacks during a rolling deployment.

This phase also exposes the already-authoritative `clock_observed_at` field
through the public API response schema. No database migration is required.
