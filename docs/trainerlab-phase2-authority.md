# TrainerLab Phase II: AI commit ownership

This first Phase II increment makes AI results conditional proposals. It does not
replace the existing domain models, outbox, or REST snapshot contract.

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

## Remaining Phase II work

- Serialize all instructor, guard, lifecycle, and AI mutation entry points under
  the same session transaction. Existing revision checks do not by themselves
  make every legacy writer atomic with an AI commit.
- Add a monotonic event sequence and define snapshot/event reconciliation across
  all writers, including corrections and authoritative client event IDs.
- Carry stronger command provenance through intervention assessments and debrief.
- Complete frontend overlay reconciliation and test on macOS/iOS.

The matching frontend increment rejects responses from a previous scenario or
console lifetime and snapshots older than known lifecycle revisions. Rejected
snapshots do not falsely update the last-successful-refresh timestamp.
