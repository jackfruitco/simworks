# TrainerLab Phase VI: confirmed voice actions

MedSim supports instructor-initiated dictation on iPhone and iPad. One capture
produces an editable draft; it cannot mutate the scenario. The instructor reviews
the transcript, affirms that the action occurred, selects a structured intervention,
reviews the target/site/status/details, and explicitly confirms it.

## Authority and persistence

The existing `POST /api/v1/trainerlab/simulations/{id}/events/interventions/`
accepts optional `voice_provenance`:

```json
{
  "capture_id": "stable-capture-uuid",
  "source": "push_to_talk",
  "original_transcript": "Oxygen given",
  "reviewed_transcript": "Oxygen administered",
  "confirmed": true
}
```

`client_event_id` must equal `capture_id`. Missing/false confirmation, blank text,
overlong text, mismatched capture identity, and unexpected provenance fields are
rejected. The authenticated user supplies `initiated_by_id`; clients cannot
impersonate another confirmer. Existing account/session access checks apply.

The durable TrainerCommand payload retains both transcripts and the confirmed
structured request; issued_by and command timestamps identify who confirmed it
and when. The domain event links to this audit through its outbox command_id.
Only structured intervention facts enter patient state and runtime AI context.
Transcript text is not copied into intervention notes, portrayal, or AI prompts.
No new model, migration, transcription endpoint, or OrchestrAI call is needed.

The existing durable iOS command queue handles delivery, reconnect, and retries.
Capture identity plus backend uniqueness prevents duplicate interventions even
after ambiguous network outcomes. Conflicting resubmission fails with 409.
Editing a draft preserves its original transcript. After confirmation, corrections
use the existing explicit supersedes_event_id contract, retaining the old event.

## Capture and review

- Explicit start/stop capture; no ambient listening, background capture, or audio storage.
- On-device Speech recognition only. Unsupported languages/devices, permission denial,
  or microphone failure leave the existing manual intervention picker available.
- A 30-second cap, background transitions, interruptions, dismissal, and session changes
  stop capture. Late callbacks are ignored; the latest visible partial transcript is
  frozen for review. The instructor can retry if the final word was not captured.
- Deterministic vocabulary matching suggests intervention types. It does not infer
  sites, doses, target problems, effectiveness, or whether an action was completed.
- Common negation, uncertainty, and planning language suppress suggestions. This is
  an assistance heuristic, not a language safety classifier: every action still
  requires explicit instructor confirmation regardless of the wording.
- Multiple mentioned actions are reviewed separately; one capture confirms at most
  one intervention. Other learner observations remain available through existing notes.
- Voice recording requires an explicit target problem because the authoritative
  intervention API requires one. Effectiveness starts unknown.

## Rollout and validation

Deploy this backend before the companion iOS update, so voice audit metadata is
retained. Older manual clients remain compatible. No migration is required beyond
earlier phases. Speech and microphone purpose strings are included in the app.

Automated coverage includes confirmation validation, permissions, actor attribution,
audit isolation, duplicate delivery, conflicts, corrections, candidate matching,
negation/plans, transcript editing, request encoding, and queue submission.
On physical iPhone and iPad, validate permission denial, supported/unsupported locale,
audio interruption, backgrounding, capture cancellation, noisy-room recognition,
and VoiceOver. Engineering tests do not establish clinical transcription accuracy.
