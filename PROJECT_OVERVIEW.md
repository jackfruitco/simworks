# SimWorks / ChatLab – Project Overview

## Project summary
SimWorks is a Django-based training platform that delivers chat-driven clinical simulations. Users conduct scenario sessions, exchange messages (with media), and receive AI-assisted responses. The system records patient data, simulation artifacts, and feedback for review and assessment.

---

## App map

- accounts
  - Custom user model, invitations, and role/resource authorization.
- core
  - Shared utilities and API access control for external integrations.
- simcore
  - Domain models for simulations, metadata, patient demographics/history, lab/radiology results, feedback, and simulation media.
- chatlab
  - Chat sessions, messages, and message media links for conversation flows inside a simulation.
- simai
  - Storage and lifecycle for AI responses associated with simulations, including response types and token accounting.

---

## Domain model highlights

- Simulation-centric design
  - simcore.Simulation is the anchor for session state, metadata, results, and artifacts.
  - Patient data: demographics, history, lab and radiology results.
  - Media: simulation-level images and per-message media links.

- Chat workflow
  - chatlab.ChatSession groups user interaction; chatlab.Message represents each utterance.
  - Media attachments are tracked via chatlab.MessageMediaLink.

- AI responses
  - simai.Response persists provider payloads and metadata.
  - Response types include initial, reply, feedback, media, and patient-results variants.
  - Ordered per simulation with unique sequence constraints; token usage (input/output/reasoning) is tallied for analytics.

- Feedback and evaluation
  - simcore.SimulationFeedback captures user or instructor assessments tied to a simulation.

- Access and authorization
  - accounts.CustomUser with role/resource mapping for fine-grained permissions.
  - core.ApiAccessControl provides per-key enablement/limitations for API-facing features.

---

## Core features

- Chat-driven simulation sessions with message history and media.
- AI-assisted replies persisted with raw payloads and token metrics.
- Patient context (demographics/history) and clinical data (lab/rad results) embedded into scenarios.
- Role- and resource-aware access controls across apps.
- Simulation feedback capture and audit-friendly metadata.

---

## Tech stack and services

- Python 3.13, Django
- Celery + Redis for background jobs and task orchestration
- Pillow for image handling
- pytest for testing
- HTTP integrations via requests

Package management: uv (use uv commands for dependency operations and scripted runs).

---

## Conventions and notes

- Simulations own most related records (messages, AI responses, results, images) for straightforward querying and cleanup.
- AI responses store the provider’s response identifier as the primary key and the raw payload for traceability.
- Responses are strictly ordered per simulation and indexed by creation time for efficient retrieval.
- Related names are defined to make reverse lookups explicit (e.g., simulation.responses, user.responses).

---

## Development quickstart

- Install and run migrations:
  - uv run python manage.py migrate
- Start the development server:
  - uv run python manage.py runserver
- Run tests:
  - uv run pytest

Configure environment variables and credentials via your local .env or settings overrides. Use placeholders rather than real secrets in shared materials.

---

## Troubleshooting

1. Migrations: If models change, run makemigrations and migrate to keep the schema synced.
2. Data integrity: Watch for ordering and uniqueness constraints on AI responses when seeding or replaying events.
3. Media handling: Ensure Pillow and storage settings are configured for image fields.
4. Background tasks: Verify Redis connectivity and Celery worker availability for any queued operations.

---