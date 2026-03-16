# TrainerLab: Target Improvements Plan

## Context

TrainerLab is the instructor-facing module of SimWorks — a Django/OrchestrAI medical training platform. Trainers use an iPad-first REST+SSE API to manage live clinical scenarios: injecting events, steering AI behavior, monitoring patient state, and generating debriefs.

**Incoming branches inform this analysis:**
- `claude/injury-control-states-Crlch`: Adds `Problem` model separating immutable injury causes from mutable treatment lifecycle; adds `control_state` field (`uncontrolled` / `controlled` / `resolved`); restricts AI from setting `is_treated`/`is_resolved` (instructor-only authority).
- `claude/add-orca-pulse-vitals-Swb7s`: Does not yet exist — indicates a planned OrchestrAI vitals progression service is needed.
- `epic/trainerlab-mvp`: Structured intervention dictionary, event payload enrichment, expanded test coverage.

---

## Target Improvements (3–7)

### 1. Orca Pulse Vitals Service (`claude/add-orca-pulse-vitals`)

**Problem**: The `GenerateTrainerRuntimeTurn` service handles both condition changes *and* vital sign progression in a single combined AI tick. This conflates two distinct concerns: clinical event progression (injuries worsening/improving) and physiological measurement updates (heart rate, SpO2 trending).

**Improvement**: Create a dedicated `GenerateVitalsProgression` OrchestrAI service in `trainerlab/orca/services/vitals.py`:
- Focused schema: reads current conditions and active interventions, outputs only vital measurements
- Can be triggered independently from condition processing (e.g., faster cadence, on-demand by trainer)
- Supports the planned branch and avoids overloading the runtime turn with dual responsibilities
- Emits `vital.updated` events via SSE for real-time trainer monitoring

**Files to create/modify**:
- `SimWorks/apps/trainerlab/orca/services/vitals.py` (new)
- `SimWorks/apps/trainerlab/orca/schemas/vitals.py` (new)
- `SimWorks/apps/trainerlab/orca/instructions/vitals.py` (new)
- `SimWorks/api/v1/endpoints/trainerlab.py` — add `POST /simulations/{id}/run/tick/vitals/`

---

### 2. Condition Control State Mutation API

**Problem**: The incoming `injury-control-states` branch adds `Problem.control_state` (`uncontrolled` / `controlled` / `resolved`) and restricts AI from modifying `is_treated`/`is_resolved`. But there is currently no dedicated API endpoint for trainers to explicitly set these fields. The event injection flow (`POST /events/injuries/`) creates new events; it doesn't update the treatment state of existing problems.

**Improvement**: Add `PATCH /simulations/{id}/conditions/{problem_id}/` endpoint for trainers to:
- Mark a condition as `controlled` (set `is_treated=True`)
- Mark a condition as `resolved` (set `is_resolved=True`)
- Update severity or description
- Emits `condition.updated` SSE event with the new `control_state`

This gives trainers direct, atomic control over patient condition lifecycle — critical for accurately reflecting real-world interventions (e.g., a tourniquet was applied, mark hemorrhage as controlled).

**Files to modify**:
- `SimWorks/api/v1/endpoints/trainerlab.py` — add PATCH endpoint
- `SimWorks/api/v1/schemas/trainerlab.py` — add `ProblemUpdateIn` schema
- `SimWorks/apps/trainerlab/services.py` — add `update_problem_control_state()`
- `SimWorks/apps/trainerlab/event_payloads.py` — add `condition.updated` payload

---

### 3. Tick Visibility & Manual Tick Trigger

**Problem**: Trainers have no visibility into *when* the next AI turn will fire. The `TrainerSession.tick_interval_seconds` is set at session creation, and `last_ai_tick_at` is stored in `runtime_state_json`, but neither `next_tick_at` nor elapsed countdown is surfaced to clients. Trainers also cannot trigger an immediate AI tick — they must wait for the timer.

**Improvement**:
1. **Expose `next_tick_at`** in the `GET /simulations/{id}/state/` response — computed as `last_ai_tick_at + tick_interval_seconds`
2. **Emit tick lifecycle events** via SSE: `tick.started` and `tick.completed` so trainer UI can show a live countdown/spinner
3. **Add `POST /simulations/{id}/run/tick/`** for manual tick trigger — instructor forces an immediate AI turn (useful for teaching moments, bypasses timer)

This gives trainers precise control and eliminates uncertainty about AI behavior timing.

**Files to modify**:
- `SimWorks/api/v1/endpoints/trainerlab.py` — add manual tick endpoint, enrich state response
- `SimWorks/api/v1/schemas/trainerlab.py` — add `next_tick_at` to `TrainerStateOut`
- `SimWorks/apps/trainerlab/services.py` — add `trigger_manual_tick()`
- `SimWorks/apps/trainerlab/tasks.py` — emit tick lifecycle events

---

### 4. Live Debrief Annotations

**Problem**: The existing `SimulationNote` model and `POST /events/notes/` endpoint supports free-text notes, but these are flat instructor observations. The AI-generated debrief (`GenerateDebrief`) uses the full event history as context, but has no way to distinguish which moments the instructor considered pedagogically significant. Debrief quality suffers.

**Improvement**: Add a structured `DebriefAnnotation` model and API:
- Fields: `simulation`, `user`, `timestamp` (can backdate), `learning_objective` (enum: assessment, hemorrhage_control, airway, etc.), `observation_text`, `outcome` (correct/incorrect/missed/improvised)
- Endpoint: `POST /simulations/{id}/annotations/`
- Expose annotations list to `GenerateDebrief` service as structured context
- Annotations are also displayed in the debrief response

This closes the loop between trainer observation during the simulation and the post-session debrief quality.

**Files to create/modify**:
- `SimWorks/apps/trainerlab/models.py` — add `DebriefAnnotation` model
- New migration
- `SimWorks/api/v1/endpoints/trainerlab.py` — add annotation CRUD
- `SimWorks/api/v1/schemas/trainerlab.py` — add `AnnotationIn`/`AnnotationOut`
- `SimWorks/apps/trainerlab/orca/services/debrief.py` — inject annotations into context
- `SimWorks/apps/trainerlab/orca/instructions/debrief.py` — update prompt to use annotations

---

### 5. Preset Application Diff in API Response

**Problem**: `POST /presets/{preset_id}/apply/` returns only a `TrainerCommandAck` — a minimal acknowledgment. The trainer has no immediate visibility into what changed when a preset was applied: which conditions were added, what vitals were set, which scenario parameters changed. They must poll `GET /simulations/{id}/state/` and diff manually.

**Improvement**: Enhance the preset apply response to include a structured `diff`:
```json
{
  "command_id": "...",
  "status": "processed",
  "diff": {
    "conditions_added": [...],
    "vitals_set": {...},
    "scenario_adjustments": [...]
  }
}
```

This eliminates a round-trip and gives trainers immediate confirmation of what the preset changed — critical for fast-paced scenario management.

**Files to modify**:
- `SimWorks/api/v1/endpoints/trainerlab.py` — enrich preset apply response
- `SimWorks/api/v1/schemas/trainerlab.py` — add `PresetApplyOut` with `diff` field
- `SimWorks/apps/trainerlab/services.py` — compute diff during `apply_preset()`

---

### 6. Intervention→Condition Feedback Loop via SSE

**Problem**: When an instructor injects an intervention (`POST /events/interventions/`) and targets a specific condition (via `target_problem` FK from the epic/trainerlab-mvp branch), the AI acknowledges it at the next runtime tick. But there's no structured SSE event that closes the loop: "AI assessed tourniquet on left leg — hemorrhage is now controlled." The trainer must inspect the full state snapshot to understand effectiveness.

**Improvement**: After the next runtime tick processes pending reasons including the intervention:
- Emit `intervention.assessed` SSE event containing:
  - `intervention_id`, `intervention_label`
  - `target_condition_id`, `condition_label`, new `control_state`
  - `effectiveness` (effective / partial / ineffective / unknown)
  - `ai_rationale` (brief excerpt from AI plan)

This creates clear cause-and-effect visibility for trainers monitoring interventions in real time.

**Files to modify**:
- `SimWorks/apps/trainerlab/orca/schemas/runtime.py` — add `intervention_assessments` to runtime turn output
- `SimWorks/apps/trainerlab/event_payloads.py` — add `intervention.assessed` payload
- `SimWorks/apps/trainerlab/services.py` — emit assessment events after runtime turn
- `SimWorks/api/v1/endpoints/trainerlab.py` — document new SSE event type

---

### 7. Scenario Brief Edit Endpoint

**Problem**: `ScenarioBrief` records are AI-generated by `GenerateInitialScenario` and stored in `runtime_state_json.scenario_brief`. Instructors cannot edit the read-aloud brief, environment description, or evacuation options after generation — even for small corrections or customizations. This forces trainers to either accept an imperfect AI output or restart the scenario.

**Improvement**: Add `PATCH /simulations/{id}/scenario-brief/` endpoint:
- Allows partial updates to `read_aloud_brief`, `environment`, `location_overview`, `threat_context`, `evacuation_options`, `special_considerations`
- Updates both `runtime_state_json` and the corresponding `ScenarioBrief` domain record
- Emits `scenario_brief.updated` SSE event

This is a small but high-value change — scenario briefs are read aloud to students and must be accurate.

**Files to modify**:
- `SimWorks/api/v1/endpoints/trainerlab.py` — add PATCH endpoint
- `SimWorks/api/v1/schemas/trainerlab.py` — add `ScenarioBriefUpdateIn`
- `SimWorks/apps/trainerlab/services.py` — add `update_scenario_brief()`
- `SimWorks/apps/trainerlab/event_payloads.py` — add `scenario_brief.updated` payload

---

## Priority Ordering

| # | Improvement | Impact | Effort | Why Now |
|---|-------------|--------|--------|---------|
| 1 | Orca Pulse Vitals Service | High | High | Planned branch; decouples vitals from runtime turn |
| 2 | Condition Control State Mutation | High | Medium | Required companion to injury-control-states branch |
| 3 | Tick Visibility + Manual Trigger | Medium | Low | Trainer UX gap; low implementation cost |
| 5 | Preset Apply Diff | Medium | Low | Eliminates round-trip; quick win |
| 6 | Intervention→Condition Feedback | High | Medium | Closes key UX feedback loop |
| 4 | Live Debrief Annotations | Medium | High | Improves debrief quality; new model needed |
| 7 | Scenario Brief Edit | Low | Low | Polish; read-aloud accuracy matters |

## Verification

- Run `uv run pytest tests/ -v` after each change
- Validate SSE stream manually: `curl -N /api/v1/trainerlab/simulations/{id}/events/stream/`
- Export OpenAPI: `uv run python scripts/export_openapi.py`
- Lint: `ruff check --fix . && ruff format .`
