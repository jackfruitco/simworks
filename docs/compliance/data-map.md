# MedSim Data Map

## Raw data classes
- Chat transcripts (`chatlab.Message.content`) — short-lived retention.
- Raw AI/provider payloads (`ServiceCall.request`, `ServiceCallAttempt.response_raw`, etc.) — disabled by default and retention-limited.

## Durable educational artifacts
- Simulation rows (`simcore.Simulation`).
- Feedback metadata (`simcore.SimulationFeedback`).
- Durable summaries (`simcore.SimulationSummary`).
