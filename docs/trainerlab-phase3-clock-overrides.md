# TrainerLab Phase III: simulation clock and instructor holds

`/state/` reports `runtime_snapshot.active_elapsed_seconds` as active simulation
time and `clock_observed_at` as its observation time. Clients advance the
display locally only while `status == running`; pause and completion preserve
the last active elapsed value. Historical clients can omit `clock_observed_at`.

New problems store `onset_elapsed_seconds`, which survives AI and instructor
supersession. Progression rules use active simulation time rather than the
timestamp on the latest problem row. Older problem records retain their
history; their earliest superseded row provides the best available onset
estimate. Historical pauses cannot be reconstructed from those rows.

Instructor vital events immediately replace the active measurement of that
type and may set `lock_value=true`. Both runtime and dedicated vitals AI
outputs leave held measurements alone. Releasing a hold creates a new
instructor event with `lock_value=false` and the prior measurement's
`supersedes_event_id`; stale IDs receive HTTP 409. The event and command
history document each correction. AI output cannot create a hold.

An AVPU adjustment is also applied to the patient-status projection immediately
as an instructor event; the queued runtime turn subsequently reasons from that
state. AVPU is a correction to the current observation, not a lasting hold.

Pause keeps queued instructor inputs for resume but prevents task scheduling,
claiming a runtime batch, applying a late AI response, or requesting a manual
tick. Stopping remains an explicit instructor command.

Deploy migration `0004_problem_onset_elapsed_seconds` before the updated
backend. The iOS clock field is optional during a rolling deployment.
