# Usage Guards — Developer Guide

## Overview

The guard framework (`apps/guards/`) provides centralized API usage guardrails
shared across TrainerLab and ChatLab. It enforces:

- **Inactivity autopause** (TrainerLab) — pause engine after 5 minutes of no presence
- **Plan-based runtime caps** — active elapsed time limits per product plan
- **Token usage limits** — session, user, and account level
- **Pre-session admission** — token budget check before starting TrainerLab
- **ChatLab send-lock** — lock sending when usage budget is exhausted
- **Wall-clock expiry** — hard time limit on sessions

## Key Concepts

### Active Definition

A session is "active" when:
- The client is **foregrounded / visible** (not just SSE-connected)
- A **recent heartbeat** exists (within 45 seconds)

SSE connection alone does **not** define active state.

### Guard States

| State | Meaning |
|-------|---------|
| `active` | Session is running normally |
| `idle` | Reserved for future use |
| `warning` | Inactivity warning sent (4m30s) |
| `paused_inactivity` | Autopause due to inactivity (5m) — **resumable** |
| `paused_runtime_cap` | Runtime cap reached — **not resumable** for engine progression |
| `locked_usage` | Token usage limit exceeded |
| `ended` | Terminal (wall-clock expiry or explicit end) |

### Pause Reasons

| Reason | Description |
|--------|-------------|
| `none` | Not paused |
| `inactivity` | No heartbeat for 5 minutes |
| `runtime_cap` | Active elapsed time exceeded plan limit |
| `usage_limit` | Token limit exceeded |
| `wall_clock_expiry` | Session wall-clock expired |
| `manual` | User/instructor manually paused |

### Resumable vs Terminal Pause

- **Resumable**: `paused_inactivity`, `locked_usage` — user can resume and continue
- **Terminal**: `paused_runtime_cap`, `ended` — engine progression is permanently stopped
  - The session data remains accessible
  - TrainerLab: manual record edits still allowed
  - ChatLab: transcript remains readable

## Architecture

```
┌─────────────────────────────────────────┐
│  API Endpoints (heartbeat, guard-state) │
└─────────────┬───────────────────────────┘
              │
┌─────────────▼───────────────────────────┐
│  Guard Services (services.py)           │ ← Single entry: guard_service_entry()
│  • ensure_session_presence()            │
│  • record_heartbeat()                   │
│  • evaluate_inactivity()                │
│  • evaluate_runtime_cap()               │
│  • check_pre_session_budget()           │
│  • check_chat_send_allowed()            │
│  • record_usage()                       │
└─────────────┬───────────────────────────┘
              │ uses
┌─────────────▼───────────────────────────┐
│  Decisions (decisions.py)               │ ← Stateless RuntimeGuard
│  • may_start_session?                   │
│  • may_start_runtime_operation?         │
│  • should_warn? should_pause?           │
│  • should_lock_send?                    │
│  • check_runtime_cap / usage_limits     │
└─────────────┬───────────────────────────┘
              │ reads
┌─────────────▼───────────────────────────┐
│  Policy (policy.py)                     │ ← Plan-based policy lookup
│  • resolve_policy(lab_type, product)    │
│  • GuardPolicy (frozen dataclass)       │
└─────────────────────────────────────────┘
```

## TrainerLab Paused Manual-Edit Rules

While a TrainerLab session is paused (inactivity or runtime cap):

**Allowed** (purely manual/domain-local):
- Recording interventions
- Recording annotations
- Adding assessment findings
- Adding notes
- Manual record additions

**Blocked** (triggers runtime/AI progression):
- Steer prompts
- Inject events that trigger runtime turns
- AI evaluation / grading
- Scenario adjustments

The UI must show a warning that the engine is paused and manual entries
are recording data only — not advancing the simulation.

## Limit Precedence

When multiple limits are exceeded, the **most actionable** reason is reported:

1. **Session limit** → "Session token limit reached"
2. **User limit** → "Your usage limit reached"
3. **Account limit** → "Account usage limit reached"

A request is denied if **any** enforced limit is exceeded.

## Policy Resolution

Policies are resolved from `(lab_type, product_code)` pairs:

```
lab_type + product_code → GuardPolicy (frozen dataclass)
```

Product code is resolved from the simulation's user + account entitlements
using `apps.billing.services.entitlements.get_effective_entitlements()`.

### Default Runtime Caps

| Plan | Cap |
|------|-----|
| Go plans | 20 minutes |
| Plus plans | 30 minutes |
| MedSim One Plus | 45 minutes |

Caps are based on **active elapsed time** — paused time does not count.

## Heartbeat Protocol

- Clients send `POST /api/v1/simulations/{id}/heartbeat/` every 15 seconds
- Payload: `{"client_visibility": "foreground" | "background" | "unknown"}`
- Response: current `GuardStateOut` with warnings and denial info
- Server evaluates inactivity via periodic Celery task (`check_stale_sessions`)
- Heartbeat stale threshold: 45 seconds
- Warning at 4 minutes 30 seconds
- Autopause at 5 minutes

## Usage Tracking

Usage is recorded automatically via a Django signal on `service_call_succeeded`
from `orchestrai_django`. Tokens are aggregated at three levels:

- **Session**: per-simulation totals
- **User**: per-user monthly totals
- **Account**: per-account monthly totals

Each level tracks: `input_tokens`, `output_tokens`, `reasoning_tokens`,
`total_tokens`, `service_call_count`.

The schema supports future "included quota + extra purchased quota" by keeping
usage records independent of billing models.
