# Assessments App Refactor — Implementation Plan

## Context

The simulation feedback subsystem currently persists initial post-simulation
feedback as four `SimulationFeedback` rows (a `SimulationMetadata` polymorphic
subclass) keyed by `hotwash_correct_diagnosis`,
`hotwash_correct_treatment_plan`, `hotwash_patient_experience`, and
`hotwash_overall_feedback`, with values stringified (`"True"`, `"4"`, etc.).
Continuation Q&A persists a fifth row, `hotwash_continuation_direct_answer`.
The shape is rigid (4 hardcoded keys), values are not typed, and there is no
rubric, scoring, versioning, account-scoping, or evidence model.

This refactor replaces that with a first-class `assessments` app that models
rubrics, criteria, completed assessments, per-criterion scores (with typed
values + normalized 0–1 score + evidence + rationale), and a generic source
linkage so an assessment can be tied to one-or-more simulations or other
assessments. Rubrics are seeded from per-lab YAML files (initial seed only),
then the database is the source of truth; published rubrics are immutable.

This is an approved destructive refactor: the database may be wiped, project
app migrations may be reset, the legacy `SimulationFeedback` model is removed,
and the outbox event/tool slug for feedback are renamed without backward
aliases. Third-party migrations (`packages/orchestrai_django/...`) are not
touched.

User-confirmed architectural decisions:

- Continuation Q&A creates a **separate Assessment** of
  `assessment_type="continuation_feedback"`, linked to the initial assessment
  via `AssessmentSource(source_type="assessment", role="generated_from")`.
- Both the simulation tool slug and the outbox event are renamed:
  `simulation_feedback` → `simulation_assessment`,
  `feedback.item.created` → `assessment.item.created`.

## Phase outline

The plan is delivered in phases; each phase ends with green tests on the
work it touches before the next phase starts.

1. **Phase 1 — App skeleton + models + admin + migrations** *(this file)*
2. **Phase 2 — YAML rubric seed + sync command + resolution service**
3. **Phase 3 — Persistence refactor: replace `feedback_block.py`, swap orca schema imports, rename outbox event**
4. **Phase 4 — Tool / API / serializer / template / privacy-export updates**
5. **Phase 5 — Remove `SimulationFeedback`, sweep stale `hotwash_*` references, reset project migrations**
6. **Phase 6 — End-to-end verification: fresh DB migrate, rubric sync, full pytest, manual smoke**

---

## Phase 1 — App skeleton + models + admin + migrations

### Goal

Stand up `apps.assessments` with all five models, validation logic,
constraints, admin registrations, and Phase-1 model unit tests passing —
without touching any feedback persistence yet. After this phase the new app
exists alongside the legacy `SimulationFeedback`; nothing reads from or writes
to assessments yet, and the legacy path is still live.

### Files to create

```
SimWorks/apps/assessments/__init__.py
SimWorks/apps/assessments/apps.py
SimWorks/apps/assessments/models.py
SimWorks/apps/assessments/admin.py
SimWorks/apps/assessments/migrations/__init__.py
tests/assessments/__init__.py
tests/assessments/conftest.py
tests/assessments/test_models.py
```

### Files to modify

```
SimWorks/config/settings.py        # add "apps.assessments" to INSTALLED_APPS
```

### Detailed work items

#### 1.1 `SimWorks/apps/assessments/apps.py`

```python
from django.apps import AppConfig


class AssessmentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.assessments"
    label = "assessments"
```

No `ready()` hook (per spec: do not run hidden startup seeding).

#### 1.2 `SimWorks/config/settings.py`

Add `"apps.assessments"` to `INSTALLED_APPS` immediately after `"apps.simcore"`
(line ~134) so privacy/billing/feedback can later import from it without
ordering issues.

#### 1.3 `SimWorks/apps/assessments/models.py`

Five models. Field names match the spec exactly. Imports:

```python
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
```

##### `AssessmentRubric`

Fields per spec:

| Field | Type | Notes |
|---|---|---|
| `id` | `BigAutoField` | default PK |
| `slug` | `SlugField(max_length=120)` | |
| `name` | `CharField(max_length=200)` | |
| `description` | `TextField(blank=True, default="")` | |
| `scope` | `CharField(choices=Scope, default=GLOBAL)` | `global`, `account` |
| `account` | `FK(accounts.Account, null=True, blank=True, on_delete=CASCADE)` | |
| `lab_type` | `CharField(max_length=40, blank=True, db_index=True)` | |
| `assessment_type` | `CharField(max_length=60, db_index=True)` | |
| `version` | `PositiveIntegerField(default=1)` | |
| `status` | `CharField(choices=Status, default=DRAFT)` | `draft`, `published`, `archived` |
| `based_on` | `FK("self", null=True, blank=True, on_delete=SET_NULL)` | |
| `created_by` | `FK(AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL, related_name="rubrics_created")` | |
| `updated_by` | `FK(AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL, related_name="rubrics_updated")` | |
| `seed_source_app` | `CharField(max_length=80, blank=True, default="")` | |
| `seed_source_path` | `CharField(max_length=255, blank=True, default="")` | |
| `seed_checksum` | `CharField(max_length=64, blank=True, default="")` | sha256 hex |
| `created_at` | `auto_now_add` | |
| `updated_at` | `auto_now` | |
| `published_at` | `DateTimeField(null=True, blank=True)` | |

Constraints:

- `UniqueConstraint(fields=["slug", "version"], condition=Q(account__isnull=True), name="uniq_rubric_global_slug_version")`
- `UniqueConstraint(fields=["account", "slug", "version"], condition=Q(account__isnull=False), name="uniq_rubric_account_slug_version")`
- `CheckConstraint(name="rubric_account_matches_scope", check=(Q(scope="account") & Q(account__isnull=False)) | (Q(scope="global") & Q(account__isnull=True)))`

Indexes:

- `["lab_type", "assessment_type", "status"]`
- `["account", "status"]`

Immutability behavior (`save()` + `clean()`):

- `clean()` validates scope/account pairing.
- `save()` reloads the previous DB row; if previous `status == PUBLISHED`,
  raise `ValidationError` for any change to `slug`, `name`, `description`,
  `lab_type`, `assessment_type`, `version`, `scope`, `account`,
  `seed_checksum`, `based_on`, `published_at`. Allow only `status` →
  `ARCHIVED` and `updated_by`/`updated_at` updates. Block
  `PUBLISHED → DRAFT`.
- On transition to `PUBLISHED`, set `published_at = timezone.now()` if not
  already set.
- Always run `self.full_clean()` from `save()`.

##### `AssessmentCriterion`

| Field | Type | Notes |
|---|---|---|
| `rubric` | `FK(AssessmentRubric, on_delete=CASCADE, related_name="criteria")` | |
| `slug` | `SlugField(max_length=80)` | |
| `label` | `CharField(max_length=200)` | |
| `description` | `TextField(blank=True, default="")` | |
| `category` | `CharField(max_length=60, blank=True, default="")` | |
| `value_type` | `CharField(choices=ValueType)` | `bool`, `int`, `decimal`, `text`, `enum`, `json` |
| `min_value` | `DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)` | applies to int/decimal |
| `max_value` | `DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)` | |
| `allowed_values` | `JSONField(default=list, blank=True)` | enum list |
| `weight` | `DecimalField(max_digits=6, decimal_places=3, default=Decimal("1.000"))` | |
| `sort_order` | `PositiveIntegerField(default=0)` | |
| `required` | `BooleanField(default=True)` | |
| `include_in_user_summary` | `BooleanField(default=True)` | |
| `created_at` | `auto_now_add` | |
| `updated_at` | `auto_now` | |

Constraints:

- `UniqueConstraint(fields=["rubric", "slug"], name="uniq_criterion_rubric_slug")`
- `CheckConstraint(check=Q(weight__gte=0), name="criterion_weight_nonnegative")`

Validation (`clean()`):

- `enum` `value_type` requires non-empty `allowed_values`; `bool`/`int`/`decimal`/`text`/`json` require `allowed_values == []`.
- For `int`/`decimal`: if both `min_value` and `max_value` set, enforce `min_value <= max_value`.
- `min_value`/`max_value` must be null for non-numeric types.

Immutability (`save()`):

- If `self.pk` and parent rubric is `PUBLISHED`, raise `ValidationError`
  unless this is the initial create (`pk is None`). Also block creating new
  criteria on a published rubric.
- Run `self.full_clean()`.

##### `Assessment`

| Field | Type | Notes |
|---|---|---|
| `rubric` | `FK(AssessmentRubric, on_delete=PROTECT, related_name="assessments")` | |
| `account` | `FK(accounts.Account, on_delete=CASCADE, related_name="assessments")` | |
| `assessed_user` | `FK(AUTH_USER_MODEL, on_delete=CASCADE, related_name="assessments_received")` | |
| `created_by` | `FK(AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL, related_name="assessments_authored")` | |
| `assessment_type` | `CharField(max_length=60, db_index=True)` | |
| `lab_type` | `CharField(max_length=40, blank=True, db_index=True)` | |
| `period_start` | `DateTimeField(null=True, blank=True)` | |
| `period_end` | `DateTimeField(null=True, blank=True)` | |
| `overall_summary` | `TextField(blank=True, default="")` | |
| `overall_score` | `DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)` | normalized 0–1 |
| `generated_by_service` | `CharField(max_length=120, blank=True, default="")` | |
| `source_attempt` | `FK("orchestrai_django.ServiceCallAttempt", null=True, blank=True, on_delete=SET_NULL, related_name="assessments")` | |
| `created_at` | `auto_now_add` | |
| `updated_at` | `auto_now` | |

Constraints:

- `CheckConstraint(name="assessment_overall_score_in_unit", check=Q(overall_score__isnull=True) | (Q(overall_score__gte=0) & Q(overall_score__lte=1)))`

Indexes:

- `["account", "lab_type", "assessment_type"]`
- `["assessed_user", "lab_type"]`
- `["rubric"]`

##### `AssessmentCriterionScore`

| Field | Type | Notes |
|---|---|---|
| `assessment` | `FK(Assessment, on_delete=CASCADE, related_name="criterion_scores")` | |
| `criterion` | `FK(AssessmentCriterion, on_delete=PROTECT, related_name="scores")` | |
| `value_bool` | `BooleanField(null=True, blank=True)` | |
| `value_int` | `IntegerField(null=True, blank=True)` | |
| `value_decimal` | `DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)` | |
| `value_text` | `TextField(blank=True, default="")` | enum stores in here |
| `value_json` | `JSONField(null=True, blank=True)` | |
| `score` | `DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)` | normalized 0–1 |
| `rationale` | `TextField(blank=True, default="")` | |
| `evidence` | `JSONField(default=list, blank=True)` | list of `{type, message_id, quote, reason}` per spec; documented in field `help_text` |
| `created_at` | `auto_now_add` | |
| `updated_at` | `auto_now` | |

Constraints:

- `UniqueConstraint(fields=["assessment", "criterion"], name="uniq_score_assessment_criterion")`
- `CheckConstraint(name="score_in_unit", check=Q(score__isnull=True) | (Q(score__gte=0) & Q(score__lte=1)))`

Validation (`clean()`):

1. `criterion.rubric_id == assessment.rubric_id` else `ValidationError`.
2. Exactly one value field populated, matching `criterion.value_type`:
   - `bool` → `value_bool is not None`, all others empty/null.
   - `int` → `value_int is not None`.
   - `decimal` → `value_decimal is not None`.
   - `text` → `value_text != ""`.
   - `enum` → `value_text != ""` AND `value_text in criterion.allowed_values`.
   - `json` → `value_json is not None`.
3. Numeric types: enforce `criterion.min_value`/`max_value` if set.

`save()` runs `full_clean()`.

`evidence` `help_text`:

```
List of evidence references. Expected shape:
[
  {
    "type": "message",
    "message_id": 123,
    "quote": "I think it's reflux.",
    "reason": "Missed possible cardiac red flag."
  }
]
```

##### `AssessmentSource`

| Field | Type | Notes |
|---|---|---|
| `assessment` | `FK(Assessment, on_delete=CASCADE, related_name="sources")` | |
| `source_type` | `CharField(choices=SourceType)` | `simulation`, `assessment` |
| `simulation` | `FK("simcore.Simulation", null=True, blank=True, on_delete=SET_NULL, related_name="assessment_sources")` | |
| `source_assessment` | `FK("assessments.Assessment", null=True, blank=True, on_delete=SET_NULL, related_name="referenced_by_sources")` | |
| `role` | `CharField(choices=Role, default=PRIMARY)` | `primary`, `contributing`, `generated_from`, `evidence` |
| `notes` | `TextField(blank=True, default="")` | |
| `snapshot` | `JSONField(default=dict, blank=True)` | |
| `created_at` | `auto_now_add` | |

Constraints:

- `UniqueConstraint(fields=["assessment", "role"], condition=Q(role="primary"), name="uniq_primary_source_per_assessment")`

Indexes:

- `["assessment", "role"]`
- `["simulation"]`
- `["source_assessment"]`

Validation (`clean()`):

- `source_type == "simulation"`: `simulation_id` set, `source_assessment_id is None`.
- `source_type == "assessment"`: `source_assessment_id` set, `simulation_id is None`.
- `source_assessment_id != assessment_id` (no self-reference).

`save()` runs `full_clean()`.

#### 1.4 `SimWorks/apps/assessments/admin.py`

- `AssessmentRubricAdmin`: list_display includes `slug`, `name`, `version`,
  `scope`, `lab_type`, `assessment_type`, `status`, `published_at`,
  `account`. `list_filter`: `status`, `scope`, `lab_type`, `assessment_type`.
  `search_fields`: `slug`, `name`. Inline `AssessmentCriterionInline`
  (TabularInline). Override `get_readonly_fields(obj)` so when
  `obj.status == PUBLISHED` every field except `status` is readonly.
- `AssessmentAdmin`: list_display `id`, `assessment_type`, `lab_type`,
  `rubric`, `assessed_user`, `account`, `overall_score`, `created_at`.
  `list_filter` on `assessment_type`, `lab_type`. Inline
  `AssessmentCriterionScoreInline` and `AssessmentSourceInline` (read-only
  for now).
- All admins set `readonly_fields` to include audit timestamps.

#### 1.5 `SimWorks/apps/assessments/migrations/__init__.py`

Empty file — guarantees the package; the actual `0001_initial.py` will be
generated in this phase by running `uv run python SimWorks/manage.py
makemigrations assessments`. Phase 1 ships that generated migration.

#### 1.6 `tests/assessments/conftest.py`

Fixtures:

- `account` (db) — minimal `accounts.Account`.
- `user` (db, user_role) — reuses the role+user pattern from
  `tests/chatlab/test_message_flow.py`.
- `draft_rubric` — a `DRAFT` global `AssessmentRubric` with three criteria
  (`bool`, `int 0..5`, `enum`) for value-type coverage.
- `published_rubric` — same shape but published.
- `simulation` — minimal `simcore.Simulation` linked to `account` + `user`.

#### 1.7 `tests/assessments/test_models.py`

Tests (all `@pytest.mark.django_db`, marker `integration`):

- `test_rubric_global_unique_slug_version` — same `slug`+`version` and `account=None` raises IntegrityError; differing `version` succeeds.
- `test_rubric_account_unique_slug_version` — same `account`+`slug`+`version` raises; different `account` allowed.
- `test_rubric_scope_account_constraint` — `scope=ACCOUNT, account=None` rejected; `scope=GLOBAL, account=<acct>` rejected.
- `test_published_rubric_locked_fields_immutable` — publish, attempt to change `name` raises `ValidationError`.
- `test_published_rubric_can_archive` — publish, then `status=ARCHIVED` saves; `published_at` preserved.
- `test_published_rubric_cannot_revert_to_draft` — raises `ValidationError`.
- `test_published_at_auto_set_on_publish` — saving with `status=PUBLISHED` sets `published_at`.
- `test_criterion_unique_slug_per_rubric` — duplicate slug raises IntegrityError.
- `test_criterion_enum_requires_allowed_values` — empty list raises.
- `test_criterion_min_max_only_on_numeric_types` — text/json with `min_value` set raises.
- `test_criterion_min_le_max` — `min_value=5, max_value=3` raises.
- `test_criterion_locked_when_rubric_published` — editing label of criterion under published rubric raises.
- `test_score_value_field_must_match_value_type` — bool criterion with `value_int=1` raises.
- `test_score_int_range_enforced` — `min_value=0, max_value=5`, `value_int=6` raises.
- `test_score_decimal_range_enforced` — analogous for decimal.
- `test_score_enum_must_be_in_allowed_values` — `value_text` not in list raises.
- `test_score_rubric_mismatch_rejected` — criterion from rubric A, assessment using rubric B raises.
- `test_score_unique_per_assessment_criterion` — duplicate raises IntegrityError.
- `test_score_check_constraint_zero_to_one` — `score=Decimal("1.5")` raises IntegrityError on raw `objects.create` bypassing `clean()`.
- `test_assessment_overall_score_check_constraint` — analogous.
- `test_source_simulation_requires_simulation_fk` — missing `simulation` raises.
- `test_source_assessment_requires_source_assessment_fk` — missing `source_assessment` raises.
- `test_source_simulation_must_not_set_source_assessment` — both set raises.
- `test_source_no_self_reference` — raises.
- `test_source_unique_primary_per_assessment` — second `role=PRIMARY` row raises IntegrityError.

### Phase-1 verification

Run from repo root:

1. `uv run python SimWorks/manage.py makemigrations assessments`
   → produces `SimWorks/apps/assessments/migrations/0001_initial.py`.
2. `uv run python SimWorks/manage.py check` → clean.
3. `uv run python SimWorks/manage.py migrate` → applies cleanly on a fresh DB
   (legacy `SimulationFeedback` still exists; that's fine for Phase 1).
4. `uv run pytest tests/assessments -q` → all green.
5. `git diff --check` → no whitespace issues.
6. Sanity: `uv run python SimWorks/manage.py shell -c "from apps.assessments.models import AssessmentRubric, AssessmentCriterion, Assessment, AssessmentCriterionScore, AssessmentSource; print('ok')"`.

Phase 1 does **not** touch `apps.simcore`, the orca persist functions, the
outbox event registry, the tools subsystem, or any test outside
`tests/assessments/`. The legacy `SimulationFeedback` flow remains live and
unchanged at the end of this phase.

---

## Phase 2 — YAML rubric seed + sync command + resolution service

### Goal

Add the per-lab YAML seed format, the `sync_assessment_rubrics` management
command that discovers and imports them, and the `resolve_rubric` service
that consumers will call in Phase 3. After this phase a fresh DB plus
`migrate` plus `sync_assessment_rubrics` produces a published
`chatlab_initial_feedback` rubric (v1) with three criteria. Persistence is
still untouched — Phase 3 connects this to the orca pipeline.

### Files to create

```
SimWorks/apps/chatlab/rubrics/initial_feedback_v1.yaml
SimWorks/apps/assessments/services/__init__.py
SimWorks/apps/assessments/services/rubric_resolution.py
SimWorks/apps/assessments/services/scoring.py
SimWorks/apps/assessments/management/__init__.py
SimWorks/apps/assessments/management/commands/__init__.py
SimWorks/apps/assessments/management/commands/sync_assessment_rubrics.py
tests/assessments/test_rubric_resolution.py
tests/assessments/test_scoring.py
tests/assessments/test_sync_command.py
```

(Note: `apps/chatlab/rubrics/` does not need an `__init__.py` — discovery is
filesystem-based via `Path(app_config.path) / "rubrics"`.)

### Files to modify

```
pyproject.toml                          # add "pyyaml>=6.0" to [project] dependencies
tests/assessments/conftest.py           # add tmp-rubric-dir fixture for sync tests
```

After editing `pyproject.toml`, run `uv sync` (already on lockfile via
transitive deps; this promotes it to a direct dep).

### Detailed work items

#### 2.1 `pyproject.toml`

Append `"pyyaml>=6.0"` to the `[project] dependencies` array. PyYAML is
already in `uv.lock` as a transitive sub-dependency (verified at
`uv.lock:2055`); promoting it to a direct dependency makes the import
contract explicit.

#### 2.2 `SimWorks/apps/chatlab/rubrics/initial_feedback_v1.yaml`

```yaml
slug: chatlab_initial_feedback
name: ChatLab Initial Feedback
description: Initial post-simulation assessment for ChatLab sessions.
scope: global
lab_type: chatlab
assessment_type: initial_feedback
version: 1
status: published

criteria:
  - slug: correct_diagnosis
    label: Correct Diagnosis
    description: >
      Whether the learner identified the expected diagnosis or a
      sufficiently close working diagnosis during the simulation.
    category: clinical_reasoning
    value_type: bool
    weight: 1
    required: true
    include_in_user_summary: true
    sort_order: 10

  - slug: correct_treatment_plan
    label: Correct Treatment Plan
    description: >
      Whether the learner recommended an appropriate treatment plan
      for the scenario.
    category: treatment
    value_type: bool
    weight: 1
    required: true
    include_in_user_summary: true
    sort_order: 20

  - slug: patient_experience
    label: Patient Experience
    description: >
      Communication quality, empathy, clarity, and patient-centeredness
      across the encounter.
    category: communication
    value_type: int
    min_value: 0
    max_value: 5
    weight: 1
    required: true
    include_in_user_summary: true
    sort_order: 30
```

Per spec, `overall_feedback` is intentionally **not** modeled as a
criterion — it lands in `Assessment.overall_summary` (Phase 3).

#### 2.3 `SimWorks/apps/assessments/services/__init__.py`

```python
from .rubric_resolution import RubricNotFoundError, resolve_rubric
from .scoring import compute_overall_score, normalize_criterion_value

__all__ = [
    "RubricNotFoundError",
    "compute_overall_score",
    "normalize_criterion_value",
    "resolve_rubric",
]
```

#### 2.4 `SimWorks/apps/assessments/services/rubric_resolution.py`

```python
from django.db.models import Case, IntegerField, Q, When

from apps.assessments.models import AssessmentRubric


class RubricNotFoundError(LookupError):
    """Raised when no published rubric matches the resolution criteria."""


def resolve_rubric(*, account, lab_type: str, assessment_type: str) -> AssessmentRubric:
    """Resolve the rubric to use for the given account / lab / assessment type.

    Resolution order:
      1. Highest-version PUBLISHED account-scoped rubric matching
         (account, lab_type, assessment_type).
      2. Otherwise highest-version PUBLISHED global rubric matching
         (lab_type, assessment_type).

    Raises RubricNotFoundError if no candidate is found.
    """
    queryset = (
        AssessmentRubric.objects.filter(
            status=AssessmentRubric.Status.PUBLISHED,
            lab_type=lab_type,
            assessment_type=assessment_type,
        )
        .filter(
            Q(scope=AssessmentRubric.Scope.ACCOUNT, account=account)
            | Q(scope=AssessmentRubric.Scope.GLOBAL, account__isnull=True)
        )
        .annotate(
            scope_priority=Case(
                When(scope=AssessmentRubric.Scope.ACCOUNT, then=0),
                default=1,
                output_field=IntegerField(),
            )
        )
        .order_by("scope_priority", "-version", "-published_at")
    )

    rubric = queryset.first()
    if rubric is None:
        raise RubricNotFoundError(
            f"No published rubric for lab_type={lab_type!r} "
            f"assessment_type={assessment_type!r} account={account!r}."
        )
    return rubric
```

Notes:

- A single ORM query, indexed by the existing
  `["lab_type", "assessment_type", "status"]` index from Phase 1.
- The `account` arg may be `None`; in that case only global rubrics qualify
  (the `Q(scope=ACCOUNT, account=None)` branch matches nothing because
  Phase-1 constraints forbid `scope=ACCOUNT` with `account IS NULL`).

#### 2.5 `SimWorks/apps/assessments/services/scoring.py`

```python
from decimal import Decimal
from typing import Iterable

from apps.assessments.models import AssessmentCriterion, AssessmentCriterionScore


def normalize_criterion_value(
    criterion: AssessmentCriterion,
    *,
    value_bool: bool | None = None,
    value_int: int | None = None,
    value_decimal: Decimal | None = None,
    value_text: str = "",
    value_json=None,
) -> Decimal | None:
    """Map a typed criterion value onto a normalized 0..1 score.

    - bool      -> 1 if True else 0
    - int/decimal with both min_value and max_value set -> clamped linear
      normalization. Returns 0 when min == max.
    - int/decimal without bounds, enum, text, json -> None (caller may
      attach a manually authored score).
    """
    vt = criterion.value_type

    if vt == AssessmentCriterion.ValueType.BOOL:
        if value_bool is None:
            return None
        return Decimal("1") if value_bool else Decimal("0")

    if vt in {AssessmentCriterion.ValueType.INT, AssessmentCriterion.ValueType.DECIMAL}:
        raw = value_int if vt == AssessmentCriterion.ValueType.INT else value_decimal
        if raw is None or criterion.min_value is None or criterion.max_value is None:
            return None
        lo = Decimal(criterion.min_value)
        hi = Decimal(criterion.max_value)
        v = Decimal(raw)
        if hi == lo:
            return Decimal("0")
        normalized = (v - lo) / (hi - lo)
        if normalized < 0:
            return Decimal("0")
        if normalized > 1:
            return Decimal("1")
        # Quantize to model precision (3 decimal places).
        return normalized.quantize(Decimal("0.001"))

    return None


def compute_overall_score(
    criterion_scores: Iterable[AssessmentCriterionScore],
) -> Decimal | None:
    """Weighted mean of non-null criterion scores, weighted by criterion.weight.

    Returns None if every score is None or all weights are zero.
    """
    total_weight = Decimal("0")
    weighted_sum = Decimal("0")
    for cs in criterion_scores:
        if cs.score is None:
            continue
        weight = Decimal(cs.criterion.weight)
        if weight <= 0:
            continue
        total_weight += weight
        weighted_sum += weight * cs.score
    if total_weight == 0:
        return None
    return (weighted_sum / total_weight).quantize(Decimal("0.001"))
```

#### 2.6 `SimWorks/apps/assessments/management/commands/sync_assessment_rubrics.py`

Behavior:

- Iterate `django.apps.apps.get_app_configs()`; skip third-party
  (`orchestrai_django`, `imagekit`, `daphne`, `channels`, `allauth*`, etc.)
  by checking `app_config.name.startswith("apps.")` — only project apps own
  rubric YAML.
- For each project app, look at `Path(app_config.path) / "rubrics"` and
  glob `*.yaml`.
- For each YAML file, parse with `yaml.safe_load`; validate required
  top-level keys: `slug`, `name`, `lab_type`, `assessment_type`, `version`,
  `scope`, `status`, `criteria`. Reject `scope=account` (file-seeded
  rubrics are always global; account-scoped rubrics are admin-managed).
- Compute `seed_checksum = sha256(canonical_yaml_bytes).hexdigest()`. Use
  `yaml.safe_dump(parsed, sort_keys=True, default_flow_style=False)` to
  produce stable bytes regardless of whitespace.
- Resolve the existing rubric by
  `(slug, version, lab_type, assessment_type, scope=GLOBAL, account=None)`.
- Branches:
  - **Not present** → create `AssessmentRubric` with
    `seed_source_app=app_config.label`, `seed_source_path=relative_path`,
    `seed_checksum=…`. If YAML `status == published`, the model's `save()`
    will set `published_at`. Then create all criteria.
  - **Exists, status=draft** →
    - `seed_checksum` matches: no-op (count as `unchanged`).
    - Differs: delete existing criteria, recreate from YAML, update rubric
      `name`/`description`/`status`/`seed_checksum`. Phase-1 immutability
      rules don't apply because the rubric is `DRAFT`.
  - **Exists, status=published** →
    - `seed_checksum` matches: no-op.
    - Differs and `--create-draft-on-change` not set: raise
      `CommandError("Refusing to mutate published rubric '<slug>' v<version>; "
      "the YAML at <path> differs from the published seed_checksum. Re-run "
      "with --create-draft-on-change to create a new draft version.")`.
    - Differs and `--create-draft-on-change` set: create a new
      `AssessmentRubric` row at `version=existing.version + 1`,
      `status=DRAFT`, `based_on=existing`, copy criteria from YAML, set
      `seed_*` fields.
  - **Exists, status=archived** → same rule as `published` (immutable).

Flags:

- `--app <label>`: only scan that one app.
- `--dry-run`: parse and validate; report intended actions; no DB writes.
  Wraps the entire operation in `transaction.atomic` then `transaction.set_rollback(True)` at end.
- `--create-draft-on-change`: see above.

PyYAML import guard:

```python
try:
    import yaml  # PyYAML
except ImportError as exc:
    raise CommandError(
        "PyYAML is required for sync_assessment_rubrics. "
        "Add 'pyyaml>=6.0' to pyproject.toml dependencies and run `uv sync`."
    ) from exc
```

Output format mirrors `seed_roles.py`:

- `self.stdout.write(self.style.SUCCESS(f"  + created {slug} v{version}"))`
- `self.stdout.write(self.style.WARNING(f"  ~ updated draft {slug} v{version}"))`
- `self.stdout.write(f"  · unchanged {slug} v{version}")`
- Final summary: `created=X updated=Y unchanged=Z drafted=W`.

#### 2.7 `tests/assessments/test_rubric_resolution.py`

All `@pytest.mark.django_db`. Reuses `account`, `published_rubric`,
`draft_rubric` fixtures from Phase 1 + a new `account_b` fixture.

- `test_resolves_global_published_rubric` — single global published; resolved.
- `test_prefers_account_scoped_over_global` — both exist for same lab/type;
  account-scoped wins.
- `test_falls_back_to_global_when_account_has_no_rubric` — only global
  exists; account=`account_b` resolves global.
- `test_higher_version_wins_among_global` — v1 + v2 both published; returns v2.
- `test_higher_version_wins_among_account_scoped` — analogous.
- `test_ignores_draft_rubrics` — only draft exists → `RubricNotFoundError`.
- `test_ignores_archived_rubrics` — only archived exists → raises.
- `test_account_scoped_for_other_account_not_returned` — account-A rubric
  is not selected when resolving for `account_b`; falls back to global.
- `test_lab_type_mismatch_raises` — rubric for `chatlab` not selected when
  resolving `trainerlab`.
- `test_assessment_type_mismatch_raises` — analogous.
- `test_account_none_only_matches_global` — `account=None` only resolves
  global rubrics.

#### 2.8 `tests/assessments/test_scoring.py`

Pure unit tests (`@pytest.mark.unit` — no DB; build criterion stubs via
`Mock` or via lightweight in-memory factories that don't require save).

Where DB is convenient (e.g., to exercise the real model `clean()` paths)
use `@pytest.mark.integration` and `@pytest.mark.django_db`.

- `test_normalize_bool_true_returns_one` / `_false_returns_zero`.
- `test_normalize_bool_none_returns_none`.
- `test_normalize_int_with_bounds` — value=4, min=0, max=5 → Decimal("0.800").
- `test_normalize_int_clamped_below_min` — value=-1 → 0.
- `test_normalize_int_clamped_above_max` — value=99 → 1.
- `test_normalize_int_without_bounds_returns_none`.
- `test_normalize_decimal_with_bounds`.
- `test_normalize_min_equals_max_returns_zero`.
- `test_normalize_text_returns_none`, `test_normalize_enum_returns_none`,
  `test_normalize_json_returns_none`.
- `test_compute_overall_weighted_mean` — three scores 1.0/0.0/0.8 with
  weights 1/1/1 → 0.600. With weights 2/1/1 → (2+0+0.8)/4 = 0.700.
- `test_compute_overall_skips_none_scores`.
- `test_compute_overall_returns_none_when_all_none`.
- `test_compute_overall_zero_weights_excluded`.

#### 2.9 `tests/assessments/test_sync_command.py`

Uses a temporary "fake" Django app pointing at `tmp_path` to drop YAML
files into a `rubrics/` subdir, and a real run against the bundled
`apps/chatlab/rubrics/initial_feedback_v1.yaml`. Pattern:

```python
@pytest.fixture
def fake_app(tmp_path, monkeypatch):
    """Patch one app config's `path` to a tmp dir with a rubrics/ subfolder."""
    rubrics = tmp_path / "rubrics"
    rubrics.mkdir()
    monkeypatch.setattr(
        "django.apps.apps.get_app_config('common').path", str(tmp_path)
    )  # or override via a simple wrapper
    return rubrics
```

Tests (all `@pytest.mark.django_db`, `@pytest.mark.integration`):

- `test_command_creates_rubric_from_chatlab_yaml` — run command with no
  flags; assert one published `AssessmentRubric` with slug
  `chatlab_initial_feedback` v1 and three criteria with correct slugs,
  `value_type`, `sort_order`, `min_value`/`max_value`.
- `test_criteria_persisted_in_sort_order`.
- `test_published_at_set_when_status_published`.
- `test_seed_metadata_recorded` — `seed_source_app == "chatlab"`,
  `seed_source_path` ends with `initial_feedback_v1.yaml`, `seed_checksum`
  is 64-char hex.
- `test_rerun_unchanged_is_noop` — second run reports `unchanged=1`,
  no new rows.
- `test_draft_yaml_change_replaces_criteria` — pre-create a `DRAFT` rubric
  manually, write a YAML with one fewer criterion, rerun → criteria count
  matches new YAML and checksum updated.
- `test_published_yaml_change_fails_loudly` — pre-create a published
  rubric with a different `seed_checksum`, write a YAML for same
  `(slug, version)` with mutated criteria → raises `CommandError`
  mentioning the rubric slug, version, and YAML path.
- `test_published_change_with_create_draft_flag_creates_new_version` —
  same setup as above + `--create-draft-on-change` → original row
  unchanged, new row at `version=2`, `status=DRAFT`, `based_on=v1`.
- `test_dry_run_makes_no_changes` — DB count before/after equal even when
  YAML is new.
- `test_app_filter_skips_other_apps` — `--app chatlab` ignores tmp fake-app
  YAMLs.
- `test_missing_required_field_raises` — YAML without `lab_type`
  raises `CommandError`.
- `test_account_scope_in_yaml_rejected` — `scope: account` raises (file
  seeds are global only).
- `test_pyyaml_missing_raises_clear_error` — patch `import yaml` to raise
  `ImportError`; assert `CommandError` mentions `pyyaml>=6.0` and
  `uv sync`.

### Phase-2 verification

1. `uv sync` (after editing `pyproject.toml`) — pyyaml resolves as direct dep.
2. `uv run python SimWorks/manage.py sync_assessment_rubrics` (against the
   already-migrated DB from Phase 1) →
     `created=1 updated=0 unchanged=0 drafted=0`.
3. Re-run the same command → `created=0 updated=0 unchanged=1 drafted=0`
   (idempotent).
4. `uv run python SimWorks/manage.py sync_assessment_rubrics --dry-run` →
   no DB writes; reports planned actions.
5. `uv run pytest tests/assessments -q` — all green, including the 30+ new
   tests added in this phase.
6. `uv run python SimWorks/manage.py shell -c "from apps.assessments.services import resolve_rubric; from apps.accounts.models import Account; r = resolve_rubric(account=None, lab_type='chatlab', assessment_type='initial_feedback'); print(r.slug, r.version, r.status)"`
   prints `chatlab_initial_feedback 1 published`.

Phase 2 still does not touch `apps.simcore`, the orca persist functions, or
the outbox event registry. The legacy `SimulationFeedback` flow remains live.

---

*Phases 3–6 will be appended in subsequent passes.*
