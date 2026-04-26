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

*Phases 2–6 will be appended in subsequent passes.*
