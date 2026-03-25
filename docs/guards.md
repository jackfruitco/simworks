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
| `paused_manual` | User/instructor manually paused — **resumable** |
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

- **Resumable**: `paused_inactivity`, `paused_manual`, `locked_usage` — user can resume and continue
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

### Token Limit Enforcement

Token limits (`session_token_limit`, `user_token_limit`, `account_token_limit`) are
**optional** in `GuardPolicy`.  When a limit is `None` (the default), that scope is
**unlimited** and no enforcement occurs.  The framework is fully wired, but no plan
currently configures hard token caps — policy entries in `_POLICY_TABLE` may add them
when billing requirements are defined.

Concretely:
- `check_pre_session_budget()` always allows if no limits are configured.
- `check_chat_send_allowed()` always allows if no limits are configured.
- `check_usage_limits()` always allows if no limits are configured.

When limits _are_ set, all three checks enforce them correctly.

### UsageRecord Integrity

`UsageRecord` rows are aggregate counters (one per scope × period × lab × product).
Three conditional `UniqueConstraint`s enforce uniqueness at the DB level, making the
update-or-create upsert concurrency-safe even under parallel service call completions.

## Scheduled Tasks (Celery Beat)

`check_stale_sessions` runs every 15 seconds and:
1. Evaluates inactivity for all active TrainerLab sessions.
2. If stale, transitions `SessionPresence` to `PAUSED_INACTIVITY` **and** pauses the
   actual TrainerLab session (stopping the tick loop, freezing elapsed time).
3. Evaluates wall-clock expiry for all active sessions of any lab type.

This task **must** be scheduled in Celery Beat.  It is registered in
`config/celery.py::beat_schedule` under `check-stale-sessions-every-15-seconds`.
Without Beat running, server-authoritative inactivity enforcement will not fire.
