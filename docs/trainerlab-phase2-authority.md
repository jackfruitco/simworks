# TrainerLab Phase II: authoritative runtime commits

Phase II makes AI results conditional proposals and serializes instructor
mutations against AI commits. The domain models and durable outbox remain the
source of truth.

Runtime and vitals work each receive an independent generation token, captured
state revision, instructor-input revision, and lifecycle status before dispatch.
These values live in session runtime JSON and trusted service context. No schema
migration is required. A completion must own its generation and match the captured
state before applying any domain changes. Duplicate, replaced, unversioned, and
stale results produce an audit event without applying patient changes.

A stale runtime proposal returns its reasons to the pending queue and schedules
fresh reasoning after commit. Invalid intervention proposals are rejected without
automatic regeneration. A stale vitals proposal is discarded; the next explicit
or scheduled request must use current state. Vitals failure cannot clear runtime
ownership. Late dispatch bookkeeping cannot reactivate an already completed turn.

Intervention assessments must reference active instructor/system intervention
records from this simulation. Unknown or foreign references reject the whole
patch. AI assessment notes remain derived data and do not overwrite the original
instructor's intervention notes. Narrative grounding and initial-scenario action
validation remain separate work; this is not a claim that arbitrary generated
prose cannot hallucinate.

Deploy with old in-flight runtime work drained before resuming sessions. Old
callbacks lack generation metadata and are deliberately rejected. The existing
stuck-work recovery remains responsible for abandoned jobs; this increment does
not add a new durable job table or exactly-once broker delivery.

## Ordering and reconciliation

Instructor event injection, steering, presets, adjustments, lifecycle changes,
initial seeding transitions, and AI commits take the same session row lock.
Accepted commands commit with their state changes, projection, and outbox
events; a rolled-back mutation leaves a failed idempotency claim. Runtime
events have a per-session monotonic sequence, including a backfill migration.
The sequence travels in outbox payloads and `/state/` snapshots. The UUID
outbox cursor remains the reconnect token; the sequence orders authoritative
state within one TrainerLab session. The iOS client discards an event older
than its snapshot or latest applied event, requests a refresh on gaps, and
rejects an older snapshot even when the state revision is equal.

Intervention requests carry a stable client event ID. The backend includes it
and the command ID in event payloads, and includes the client ID in snapshots.
The client reconciles optimistic interventions against that ID; older servers
without the field retain the existing type/site matching behavior. AI can
assess a recorded intervention but cannot create a performed intervention.
The debrief command log includes original instructor payloads, while ordered
timeline highlights include event sequence and provenance.

Deploy the backend migration before a new iOS client relies on ordered events.
Older event payloads without a sequence continue to decode and use the
existing revision and cursor behavior.

The frontend also rejects responses from a previous scenario or console
lifetime and snapshots older than known lifecycle revisions. Rejected
snapshots do not falsely update the last-successful-refresh timestamp.
