# TrainerLab Phase VII: evidence-linked debrief and MVP qualification

MedSim provides a recorded-evidence review immediately after scenario completion.
AI feedback is supplementary and requires instructor review. It does not determine
whether an unrecorded learner action occurred.

## Clinical evidence and AI boundaries

The review projection includes authoritative intervention events, patient changes,
instructor annotations and notes. It excludes raw command payloads (including voice
drafts), recommendations, operational snapshots, and AI reasoning. Annotations are
explicitly instructor observations, not new performed interventions. AI-sourced
intervention creation records cannot become learner-action evidence.

All actions and observations are retained. Repeated patient changes are bounded to
the first 20 and last 280 records, with an explicit omitted-record count. The evidence
revision hashes the complete eligible history, including omitted physiology. Event
timestamps are displayed as recorded; the model cannot supply arbitrary timeline times.

OrchestrAI generates structured claims, each with exact evidence references. SimWorks
validates those references and permits a missed-care claim only when cited instructor
evidence explicitly records a missed or incorrect action. Strengths require action or
positive instructor-observation evidence. Missing records alone do not establish a miss.
Legacy narrative/list fields are derived from validated claims for older clients.

Reference validation establishes provenance, not semantic proof that prose correctly
interprets the cited record. The UI labels the report as AI-generated, exposes supporting
records, and supports instructor correction. Clinical judgment and SME validation remain
necessary; no clinical accuracy certification is implied by passing engineering tests.

## Lifecycle, corrections and delivery

- `build_summary` creates deterministic evidence without awaiting an AI provider.
- A generation UUID reserves the current evidence revision under the session lock.
- Enqueueing occurs after commit. Concurrent requests for the same in-progress report
  coalesce. Enqueue/provider failures become explicit failed state.
- Callbacks must own both generation and evidence revision. Stale/duplicate callbacks
  cannot publish a report or overwrite a newer failure/success.
- A five-minute deadline handles workers that disappear. A summary read exposes timeout
  as a failure; explicit regeneration reserves a new generation.
- Notes and annotations added after completion invalidate the old report and regenerate.
- Corrections are new instructor annotations, linked to the reviewed claim in the durable
  command audit. They preserve instructor attribution and do not mutate completed patient
  state or fabricate a performed action.
- iOS persists review requests in the existing account/session-scoped command queue.
  Reopening the summary replays the original body and idempotency key. Conflicts preserve
  the correction for explicit editing rather than silently applying it to changed evidence.
- Summary responses hide stale AI content while keeping recorded evidence available.
  Explicit failures stop polling; cancellation and response generations prevent old
  requests from replacing a newer review. Foreground entry refreshes status. Polling is
  bounded, with a pull-to-refresh message if generation outlasts observation.

## API

Retain `GET /api/v1/trainerlab/simulations/{id}/summary/`. Add:

- `evidence`, `evidence_revision`, `evidence_omitted_count`
- `debrief_status`: not_requested, generating, stale, ready, failed
- `debrief_error` (a stable failure code), `ai_debrief_revision`
- `ai_debrief.claims`: id, category, text, evidence_ids

Add `POST /api/v1/trainerlab/simulations/{id}/summary/review/` with Idempotency-Key:

```json
{
  "evidence_revision": "revision-from-summary",
  "correction": "Optional instructor observation or correction",
  "claim_id": "Optional claim being corrected"
}
```

Omit correction/claim_id to request regeneration. Access, terminal-state, evidence-revision,
claim-reference and idempotency checks are authoritative. Conflicting/stale submissions
return 409. The response is the existing TrainerCommandAck. Summary lifecycle changes use
the existing durable `simulation.summary.updated` outbox event.

No migration is needed. Existing summary JSON is upgraded on review. Deploy backend and
workers together before iOS; old unversioned in-flight callbacks are rejected. Existing
manual clients remain compatible with retained summary presentation fields.

## Performance and qualification

No additional AI pass or real-time transport is introduced. Stop/review mutations do not
wait for inference. Summary construction filters clinical events at the database, fetches
only ten legacy timeline rows, and aggregates event counts instead of loading every large
historical runtime snapshot. Polls read persisted evidence rather than rebuilding it.

Automated qualification covers:

| Area | Regression coverage |
| --- | --- |
| Launch, pause/resume, stop, annotations and summaries | TrainerLab API lifecycle tests |
| Authoritative interventions and duplicate/reordered callbacks | API command tests and AI-authority tests |
| Held overrides, active clock and progression | Phase III and V simulation tests |
| Unexpected AI output and invented evidence | Phase VII invalid-reference/miss/source tests |
| Failed enqueue, timeout, retry and stale generation | Phase VII lifecycle tests |
| Corrections, access, stale revisions and replay | Phase VII review endpoint test |
| Reconnection and event order | Existing iOS realtime/reducer/session tests |
| Review cancellation, stale responses and persisted corrections | iOS Summary tests |

Release qualification still requires physical iPhone/iPad and SME exercises: noisy-room
voice input, microphone interruption, mannequin/role-player practicality, and realistic
clinical timing. In staging, measure command acknowledgment p50/p95, evidence-ready time
after stop, debrief provider latency/failure rate, and reconnect recovery against agreed
operating conditions. No production latency figures or live-provider accuracy claims are
established by the mocked-provider test suite. The existing unrelated ChatLab voice-button
accessibility smoke failure must also be resolved before claiming a wholly green app CI.
