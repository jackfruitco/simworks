# SimWorks Schema Review + Update Plan

**Date:** 2026-01-03
**Status:** Draft for Review
**PR:** #259
**Scope:** All schemas in SimWorks Django apps + OrchestrAI integration

---

## Executive Summary

This document provides a complete inventory of schemas in the SimWorks codebase, analyzes their compatibility with the updated OrchestrAI v0.4.0 schema structure and OpenAI Responses API constraints, and proposes a concrete patch plan for modernization.

**Key Findings:**
- **3 active output schemas** currently in use (PatientInitialOutputSchema, PatientReplyOutputSchema, PatientResultsOutputSchema)
- **1 feedback schema** (HotwashInitialSchema)
- **6 reusable output item types** defined but limited reuse
- **0 critical OpenAI compatibility issues** found (all schemas are object-based with properties)
- **Moderate refactoring opportunity** to reduce duplication and improve type safety

**Recommended Approach:**
- Extract 3-5 reusable schema components for common structures
- Consolidate duplicated output item types
- Add comprehensive schema validation tests
- No breaking changes required - all updates are backward compatible

---

## 1) Schema Inventory

### 1.1 SimWorks Output Schemas (Active)

| Name | Location | Owner | Type | Used By | Persisted | Notes |
|------|----------|-------|------|---------|-----------|-------|
| **PatientInitialOutputSchema** | `chatlab/orca/schemas/patient.py` | chatlab | Pydantic + @schema | GenerateInitialResponse service | ✅ Message + Metadata | messages, metadata, llm_conditions_check |
| **PatientReplyOutputSchema** | `chatlab/orca/schemas/patient.py` | chatlab | Pydantic + @schema | GenerateReplyResponse service | ✅ Message only | image_requested, messages, llm_conditions_check |
| **PatientResultsOutputSchema** | `chatlab/orca/schemas/patient.py` | chatlab | Pydantic + @schema | Not yet wired | ✅ Metadata only | metadata, llm_conditions_check |
| **HotwashInitialSchema** | `simulation/orca/schemas/feedback.py` | simulation | Pydantic + @schema | GenerateHotwashInitialResponse | ❌ Not yet wired | llm_conditions_check, metadata (HotwashInitialBlock) |

### 1.2 Output Item Types (Reusable Components)

| Name | Location | Owner | Type | Used By | Notes |
|------|----------|-------|------|---------|-------|
| **DjangoOutputItem** | `orchestrai_django/types/django_dtos.py` | orchestrai_django | Pydantic DTO | All schemas via lists | Rich output with correlation, persistence metadata |
| **LLMConditionsCheckItem** | `simulation/orca/schemas/output_items.py` | simulation | BaseOutputItem | All 4 schemas | Generic key-value pair |
| **CorrectDiagnosisItem** | `simulation/orca/schemas/output_items.py` | simulation | BaseOutputItem | HotwashInitialBlock | Literal key, bool value |
| **CorrectTreatmentPlanItem** | `simulation/orca/schemas/output_items.py` | simulation | BaseOutputItem | HotwashInitialBlock | Literal key, bool value |
| **PatientExperienceItem** | `simulation/orca/schemas/output_items.py` | simulation | BaseOutputItem | HotwashInitialBlock | Literal key, int 0-5 |
| **OverallFeedbackItem** | `simulation/orca/schemas/output_items.py` | simulation | BaseOutputItem | HotwashInitialBlock | Literal key, string value |
| **HotwashInitialBlock** | `simulation/orca/schemas/output_items.py` | simulation | BaseOutputBlock | HotwashInitialSchema | Composite block with 4 typed items |

### 1.3 Dead/Unused Schemas

**None identified.** All defined schemas are referenced by at least one service.

### 1.4 Implicit Schemas (Inline JSON Schema)

| Location | Purpose | Notes |
|----------|---------|-------|
| `chatlab/orca/services/patient.py:125` | image_generation tool schema | Inline dict for tool input schema - low risk |

---

## 2) OrchestrAI Schema Structure Analysis

### 2.1 Current Architecture (v0.4.0)

**Schema Object Hierarchy:**
```
orchestrai.types.StrictBaseModel (Pydantic v2 BaseModel)
  ├─> orchestrai.components.schemas.base.BaseOutputItem
  │   └─> (no identity required - used for nested objects)
  │
  └─> orchestrai.components.schemas.base.BaseOutputSchema
      ├─> orchestrai.identity.IdentityMixin (provides .identity property)
      │   └─> Requires: domain, namespace, group, name
      │
      └─> orchestrai_django.components.schemas.types.DjangoBaseOutputSchema
          ├─> Adds: DjangoIdentityMixin (auto-derives namespace from app_label)
          └─> Used by: All SimWorks top-level schemas
```

**Identity Structure:**
- **Domain:** `schemas` (fixed for all output schemas)
- **Namespace:** Auto-derived from Django app label (e.g., `chatlab`, `simcore`)
- **Group:** From mixin (e.g., `standardized_patient`, `feedback`)
- **Name:** Class name (e.g., `PatientInitialOutputSchema`)

**Registration:**
- Schemas decorated with `@schema` are auto-discovered and registered
- Registry: `orchestrai.registry.schemas`
- Validation: Happens at decoration time (import)
- Caching: `_validated_schema`, `_provider_compatibility` attributes added

### 2.2 SimWorks ↔ OrchestrAI Boundary

**Current Pattern (CORRECT):**
```python
# SimWorks defines pure Pydantic models with OrchestrAI base classes
from orchestrai_django.components.schemas import DjangoBaseOutputSchema
from orchestrai_django.decorators import schema

@schema
class PatientInitialOutputSchema(ChatlabMixin, StandardizedPatientMixin, DjangoBaseOutputSchema):
    messages: list[DjangoOutputItem] = Field(..., min_length=1)
    metadata: list[DjangoOutputItem] = Field(...)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)
```

**OrchestrAI handles:**
- JSON Schema generation (`model_json_schema()`)
- Provider validation (OpenAI constraints)
- Schema adaptation (format wrapping)
- Registration and discovery

**SimWorks provides:**
- Domain-specific field definitions
- Type constraints and validation
- Identity mixins for namespace/group

---

## 3) OpenAI Responses JSON Schema Validation

### 3.1 Current Request Shape

**Location:** `orchestrai/contrib/provider_codecs/openai/responses_json.py`

**Request format:**
```python
{
    "format": {
        "type": "json_schema",
        "name": "response",
        "schema": {
            "type": "object",           # ✅ Required
            "properties": {...},        # ✅ Required
            "required": [...],          # ✅ Auto-generated by Pydantic
            "additionalProperties": False  # ✅ From StrictBaseModel
        }
    }
}
```

### 3.2 Validation Results

All 4 active schemas validated against OpenAI constraints:

| Schema | Root Type | Root Union | Has Properties | Status |
|--------|-----------|------------|----------------|--------|
| PatientInitialOutputSchema | ✅ object | ✅ none | ✅ yes | **PASS** |
| PatientReplyOutputSchema | ✅ object | ✅ none | ✅ yes | **PASS** |
| PatientResultsOutputSchema | ✅ object | ✅ none | ✅ yes | **PASS** |
| HotwashInitialSchema | ✅ object | ✅ none | ✅ yes | **PASS** |

**No compatibility issues found.**

### 3.3 Known Constraints

From `orchestrai/contrib/provider_backends/openai/schema/validate.py`:

1. ✅ **root_is_object:** Root schema must be `type: "object"`
2. ✅ **no_root_unions:** No `anyOf`/`oneOf` at root level (nested unions OK)
3. ✅ **has_properties:** Root must have `properties` field

All SimWorks schemas comply with these constraints.

---

## 4) Schema Design Review

### 4.1 Current Duplication Analysis

**Pattern 1: Repeated `messages` + `llm_conditions_check`**

All 3 patient schemas contain:
```python
messages: list[DjangoOutputItem] = Field(..., min_length=1)
llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)
```

**Pattern 2: Feedback item types are single-use**

The 4 feedback item types (CorrectDiagnosisItem, etc.) are only used in HotwashInitialBlock:
```python
class HotwashInitialBlock(DjangoBaseOutputBlock):
    correct_diagnosis: CorrectDiagnosisItem
    correct_treatment_plan: CorrectTreatmentPlanItem
    patient_experience: PatientExperienceItem
    overall_feedback: OverallFeedbackItem
```

These could be simplified to direct field definitions.

### 4.2 Proposed Reusable Components

**Component 1: PatientResponseBase (Mixin)**
```python
class PatientResponseBaseMixin(BaseModel):
    """Common fields for all patient response schemas."""
    messages: list[DjangoOutputItem] = Field(..., min_length=1)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(default_factory=list)
```

**Component 2: PatientDemographics (Future)**
```python
class PatientDemographics(DjangoBaseOutputItem):
    """Reusable patient demographics structure."""
    name: str
    age: int
    gender: str | None = None
    # ... other demographics
```

**Component 3: FeedbackBlock (Simplified)**
```python
class FeedbackBlock(DjangoBaseOutputBlock):
    """Simplified feedback without individual item classes."""
    correct_diagnosis: bool
    correct_treatment_plan: bool
    patient_experience: int = Field(..., ge=0, le=5)
    overall_feedback: str
```

### 4.3 Proposed Conventions

1. **extra="forbid"**
   - Already enforced via `StrictBaseModel` - no action needed

2. **Optional vs Required**
   - Use `Field(...)` for required (current practice ✅)
   - Use `Field(default=...)` or `= None` for optional
   - Prefer explicit `Field(default_factory=list)` for mutable defaults

3. **Enumerations**
   - Use `Literal["value1", "value2"]` for closed sets (current ✅)
   - Use `str` with validation for open sets

4. **Unions**
   - Avoid root-level unions (already compliant ✅)
   - Use discriminated unions for nested variants:
     ```python
     result: Annotated[Union[Success, Error], Field(discriminator="kind")]
     ```

5. **Versioning**
   - Not needed yet - schemas are young and stable
   - If needed: add `schema_version: Literal["v1"]` field

---

## 5) Persistence & ORM Alignment

### 5.1 Persisted Output Types

| Schema | Persists To | Idempotent | Version Tagged | Notes |
|--------|-------------|------------|----------------|-------|
| PatientInitialOutputSchema | Message + SimulationMetadata | ✅ Yes (PersistedChunk) | ❌ No | metadata items route to polymorphic models |
| PatientReplyOutputSchema | Message | ✅ Yes (PersistedChunk) | ❌ No | image_requested triggers workflow |
| PatientResultsOutputSchema | SimulationMetadata | ❌ Not yet | ❌ No | Not yet wired to persistence |
| HotwashInitialSchema | Not persisted | ❌ No | ❌ No | No persistence handler exists |

### 5.2 SimWorks Schema Ownership

**Current Approach (CORRECT):**
- SimWorks defines all schema types in `{app}/orca/schemas/`
- OrchestrAI imports SimWorks schemas via:
  - Services reference schemas directly
  - Persistence handlers import schemas
  - No circular dependencies

**Directory Structure:**
```
SimWorks/
  chatlab/orca/schemas/
    __init__.py         # Exports public schemas
    patient.py          # Patient response schemas
    output_items.py     # Empty (items moved to simulation)

  simulation/orca/schemas/
    __init__.py         # Exports public schemas
    feedback.py         # Feedback schemas
    output_items.py     # Reusable output items
```

**No changes needed** - structure is clean and avoids circular imports.

---

## 6) Patch Plan (Incremental Updates)

### Patch Set 1: Add Schema Validation Tests (1 day)
**Risk:** Low
**Files:**
- `tests/orchestrai/test_schema_validation.py` (new)
- `tests/chatlab/test_patient_schemas.py` (new)
- `tests/simulation/test_feedback_schemas.py` (new)

**Approach:**
1. Add serialization tests for all 4 active schemas
2. Add OpenAI request construction tests (mocked)
3. Add round-trip parse tests with sample outputs
4. Verify no extra keys accepted (strict mode)

**Tests to Add:**
- `test_patient_initial_schema_generates_valid_json_schema()`
- `test_patient_initial_schema_openai_compatible()`
- `test_patient_initial_schema_round_trip_parse()`
- `test_patient_reply_schema_with_image_requested()`
- `test_hotwash_schema_feedback_block_structure()`

**Migration Strategy:** None (new tests only)

**Validation:**
```bash
uv run pytest tests/orchestrai/test_schema_validation.py -v
uv run pytest tests/chatlab/test_patient_schemas.py -v
```

---

### Patch Set 2: Extract PatientResponseBaseMixin (1 day)
**Risk:** Low (refactor only, no behavior change)
**Files:**
- `chatlab/orca/schemas/mixins.py` (new)
- `chatlab/orca/schemas/patient.py` (modify)

**Approach:**
1. Create `PatientResponseBaseMixin` with common fields
2. Update all 3 patient schemas to inherit from mixin
3. Verify generated JSON schema is identical

**Before:**
```python
@schema
class PatientInitialOutputSchema(ChatlabMixin, StandardizedPatientMixin, DjangoBaseOutputSchema):
    messages: list[DjangoOutputItem] = Field(..., min_length=1)
    metadata: list[DjangoOutputItem] = Field(...)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)
```

**After:**
```python
@schema
class PatientInitialOutputSchema(PatientResponseBaseMixin, ChatlabMixin, StandardizedPatientMixin, DjangoBaseOutputSchema):
    metadata: list[DjangoOutputItem] = Field(...)
    # messages and llm_conditions_check inherited
```

**Migration Strategy:** None (backward compatible)

**Validation:**
- Existing persistence tests still pass
- Generated JSON schema unchanged (use snapshot testing)

---

### Patch Set 3: Simplify Feedback Item Types (1 day)
**Risk:** Low
**Files:**
- `simulation/orca/schemas/output_items.py` (modify)
- `simulation/orca/schemas/feedback.py` (modify)

**Approach:**
1. Remove 4 single-use item classes (CorrectDiagnosisItem, etc.)
2. Inline fields directly in HotwashInitialBlock
3. Keep semantic field names

**Before:**
```python
class HotwashInitialBlock(DjangoBaseOutputBlock):
    correct_diagnosis: CorrectDiagnosisItem
    correct_treatment_plan: CorrectTreatmentPlanItem
    patient_experience: PatientExperienceItem
    overall_feedback: OverallFeedbackItem
```

**After:**
```python
class HotwashInitialBlock(DjangoBaseOutputBlock):
    """Initial hotwash feedback block with direct field definitions."""
    correct_diagnosis: bool = Field(..., description="Whether the diagnosis was correct")
    correct_treatment_plan: bool = Field(..., description="Whether the treatment plan was correct")
    patient_experience: int = Field(..., ge=0, le=5, description="Patient experience rating (0-5)")
    overall_feedback: str = Field(..., description="Overall feedback text")
```

**Migration Strategy:** None (HotwashInitialSchema not yet persisted)

**Validation:**
- Schema validation tests confirm structure
- JSON schema generation unchanged for OpenAI

---

### Patch Set 4: Wire PatientResultsOutputSchema Persistence (Optional, 2 days)
**Risk:** Medium (new persistence path)
**Files:**
- `chatlab/orca/persist/patient.py` (modify)
- `chatlab/orca/services/patient.py` (new service)

**Approach:**
1. Create `GenerateResultsResponse` service
2. Create `PatientResultsPersistence` handler
3. Wire to existing drain worker

**Deliverables:**
- New service: `GenerateResultsResponse`
- New persistence handler: `PatientResultsPersistence`
- Tests for results persistence

**Migration Strategy:** N/A (new feature)

**Validation:**
- Persistence handler tests
- Idempotency tests
- Integration test with mocked OpenAI response

---

### Patch Set 5: Wire HotwashInitialSchema Persistence (Optional, 2 days)
**Risk:** Medium (new persistence path)
**Files:**
- `simulation/orca/persist/feedback.py` (new)

**Approach:**
1. Create `HotwashInitialPersistence` handler
2. Persist feedback block to SimulationMetadata or dedicated Feedback model
3. Wire to drain worker

**Deliverables:**
- New persistence handler: `HotwashInitialPersistence`
- Tests for feedback persistence

**Migration Strategy:** N/A (new feature)

**Validation:**
- Persistence handler tests
- Verify feedback stored correctly

---

### Patch Set 6: Add Schema Documentation (1 day)
**Risk:** None
**Files:**
- `docs/schemas/README.md` (new)
- `docs/schemas/patient_schemas.md` (new)
- `docs/schemas/feedback_schemas.md` (new)

**Approach:**
1. Document all schemas with examples
2. Document common patterns and conventions
3. Document persistence behavior

**Deliverables:**
- Schema catalog with examples
- Field-level documentation
- Persistence flow diagrams

---

## 7) Testing Requirements

### 7.1 Schema Serialization Tests

**Test:** `test_schema_generates_valid_json_schema()`
```python
def test_patient_initial_schema_generates_valid_json_schema():
    """Verify schema can generate OpenAI-compatible JSON Schema."""
    schema_json = PatientInitialOutputSchema.model_json_schema()

    # Validate structure
    assert schema_json["type"] == "object"
    assert "properties" in schema_json
    assert "required" in schema_json

    # Validate required fields present
    assert "messages" in schema_json["properties"]
    assert "metadata" in schema_json["properties"]
    assert "llm_conditions_check" in schema_json["properties"]
```

### 7.2 OpenAI Request Construction Tests

**Test:** `test_codec_builds_openai_request_format()`
```python
@pytest.mark.asyncio
async def test_codec_builds_openai_request_format():
    """Verify codec wraps schema in OpenAI format envelope."""
    from orchestrai.contrib.provider_codecs.openai.responses_json import OpenAIResponsesJsonCodec
    from orchestrai.types import Request

    req = Request(
        messages=[],
        response_schema=PatientInitialOutputSchema
    )

    codec = OpenAIResponsesJsonCodec()
    await codec.aencode(req)

    # Verify format envelope
    provider_format = req.provider_response_format
    assert provider_format["format"]["type"] == "json_schema"
    assert provider_format["format"]["name"] == "response"
    assert provider_format["format"]["schema"]["type"] == "object"
```

### 7.3 Round-Trip Parse Tests

**Test:** `test_schema_round_trip_parse()`
```python
def test_patient_initial_schema_round_trip():
    """Verify schema can parse representative OpenAI output."""
    sample_output = {
        "messages": [{
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Hello"}]
        }],
        "metadata": [],
        "llm_conditions_check": []
    }

    # Parse
    parsed = PatientInitialOutputSchema.model_validate(sample_output)

    # Verify
    assert len(parsed.messages) == 1
    assert parsed.messages[0].content[0].text == "Hello"
```

### 7.4 Safety Tests (Adapter)

**Test:** `test_format_adapter_produces_valid_json_schema()`
```python
def test_openai_format_adapter_valid():
    """Verify format adapter doesn't break JSON Schema."""
    from orchestrai.contrib.provider_backends.openai.schema.adapt import OpenaiFormatAdapter

    adapter = OpenaiFormatAdapter()
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}

    result = adapter.adapt(schema)

    # Verify wrapper
    assert "format" in result
    assert result["format"]["type"] == "json_schema"
    assert result["format"]["schema"] == schema  # Original preserved
```

### 7.5 Test Coverage Targets

| Module | Target | Critical Paths |
|--------|--------|----------------|
| `chatlab/orca/schemas/patient.py` | 95% | All schema classes |
| `simulation/orca/schemas/feedback.py` | 95% | All schema classes |
| `simulation/orca/schemas/output_items.py` | 100% | All item classes |
| `chatlab/orca/persist/patient.py` | 95% | Persistence handlers |

---

## 8) Summary for Maintainers

### 8.1 Current State

**Strengths:**
- ✅ All schemas OpenAI-compatible
- ✅ Clean identity/registration system
- ✅ Idempotent persistence via PersistedChunk
- ✅ Type-safe with Pydantic v2
- ✅ No circular dependencies

**Improvement Areas:**
- 🔶 Limited test coverage for schemas
- 🔶 Some duplication in patient schemas
- 🔶 Single-use item types could be simplified
- 🔶 2 schemas not yet wired to persistence

### 8.2 Recommended Priority

**Must Do (High Priority):**
1. **Patch Set 1:** Add schema validation tests (critical gap)
2. **Patch Set 6:** Add schema documentation

**Should Do (Medium Priority):**
3. **Patch Set 2:** Extract PatientResponseBaseMixin (reduces duplication)
4. **Patch Set 3:** Simplify feedback item types (cleaner code)

**Nice to Have (Low Priority):**
5. **Patch Set 4:** Wire PatientResultsOutputSchema persistence
6. **Patch Set 5:** Wire HotwashInitialSchema persistence

### 8.3 Risk Assessment

| Patch Set | Risk | Rollback Plan |
|-----------|------|---------------|
| 1 (Tests) | None | N/A (no code changes) |
| 2 (Mixin) | Low | Revert refactor, schemas work both ways |
| 3 (Simplify) | Low | Revert inline, schema not persisted yet |
| 4 (Results) | Medium | Disable persistence handler registration |
| 5 (Feedback) | Medium | Disable persistence handler registration |
| 6 (Docs) | None | N/A (documentation only) |

### 8.4 Timeline Estimate

**Minimum viable improvement (Patch Sets 1-3):** 3 days
**Full implementation (Patch Sets 1-6):** 7-8 days

### 8.5 Success Metrics

**Functional:**
- ✅ All schemas have test coverage >95%
- ✅ No schema validation errors in staging
- ✅ All persistence handlers tested
- ✅ Documentation complete

**Quality:**
- ✅ Zero root-level unions
- ✅ Zero inline schema dicts (tools excepted)
- ✅ All schemas registered and discoverable

**Performance:**
- ✅ Schema generation <10ms (cached)
- ✅ No measurable latency impact

---

## Appendix A: Schema Structure Reference

### Current Schema Hierarchy

```
DjangoBaseOutputSchema (abstract, with identity)
  ├─> PatientInitialOutputSchema
  │     messages: list[DjangoOutputItem]
  │     metadata: list[DjangoOutputItem]
  │     llm_conditions_check: list[LLMConditionsCheckItem]
  │
  ├─> PatientReplyOutputSchema
  │     image_requested: bool
  │     messages: list[DjangoOutputItem]
  │     llm_conditions_check: list[LLMConditionsCheckItem]
  │
  ├─> PatientResultsOutputSchema
  │     metadata: list[DjangoOutputItem]
  │     llm_conditions_check: list[LLMConditionsCheckItem]
  │
  └─> HotwashInitialSchema
        llm_conditions_check: list[LLMConditionsCheckItem]
        metadata: HotwashInitialBlock

DjangoBaseOutputBlock (no identity)
  └─> HotwashInitialBlock
        correct_diagnosis: CorrectDiagnosisItem
        correct_treatment_plan: CorrectTreatmentPlanItem
        patient_experience: PatientExperienceItem
        overall_feedback: OverallFeedbackItem

DjangoBaseOutputItem (no identity)
  ├─> LLMConditionsCheckItem
  ├─> CorrectDiagnosisItem
  ├─> CorrectTreatmentPlanItem
  ├─> PatientExperienceItem
  └─> OverallFeedbackItem
```

### Proposed Schema Hierarchy (After Refactoring)

```
DjangoBaseOutputSchema (abstract, with identity)
  ├─> PatientInitialOutputSchema (+ PatientResponseBaseMixin)
  │     metadata: list[DjangoOutputItem]
  │     # messages + llm_conditions_check inherited
  │
  ├─> PatientReplyOutputSchema (+ PatientResponseBaseMixin)
  │     image_requested: bool
  │     # messages + llm_conditions_check inherited
  │
  ├─> PatientResultsOutputSchema (+ PatientResponseBaseMixin)
  │     metadata: list[DjangoOutputItem]
  │     # llm_conditions_check inherited
  │
  └─> HotwashInitialSchema
        llm_conditions_check: list[LLMConditionsCheckItem]
        metadata: HotwashInitialBlock

DjangoBaseOutputBlock (no identity)
  └─> HotwashInitialBlock (simplified)
        correct_diagnosis: bool
        correct_treatment_plan: bool
        patient_experience: int (0-5)
        overall_feedback: str

DjangoBaseOutputItem (no identity)
  └─> LLMConditionsCheckItem (only)
```

**Items removed:** CorrectDiagnosisItem, CorrectTreatmentPlanItem, PatientExperienceItem, OverallFeedbackItem (inlined into HotwashInitialBlock)

---

## Appendix B: OpenAI Compatibility Checklist

✅ **All schemas validated against:**

1. Root type is `object` (not array, string, etc.)
2. No `anyOf`/`oneOf` at root level
3. Has `properties` field
4. Uses Pydantic `Field(...)` for required fields
5. Uses `StrictBaseModel` for `additionalProperties: false`
6. Generates valid JSON Schema via `model_json_schema()`

✅ **All schemas tagged with:**
- `_provider_compatibility: {"openai": True}`
- `_validated_schema: {...}`
- `_validated_at: "decoration"`

---

## Appendix C: Code Path Map

### Schema → Service → Codec → OpenAI

```
1. Schema Definition
   chatlab/orca/schemas/patient.py:
     @schema
     class PatientInitialOutputSchema(...)

2. Service Usage
   chatlab/orca/services/patient.py:
     @service
     class GenerateInitialResponse(...):
         response_schema = PatientInitialOutputSchema

3. Codec Encoding
   orchestrai/contrib/provider_codecs/openai/responses_json.py:
     class OpenAIResponsesJsonCodec:
         async def aencode(req):
             schema = req.response_schema._validated_schema
             adapted = OpenaiFormatAdapter().adapt(schema)

4. OpenAI Request
   orchestrai/contrib/provider_backends/openai/request_builder.py:
     request_payload = {
         "messages": [...],
         "response_format": adapted_schema  # OpenAI envelope
     }

5. Response Decoding
   orchestrai/contrib/provider_codecs/openai/responses_json.py:
     async def adecode(resp):
         return PatientInitialOutputSchema.model_validate(resp.data)

6. Persistence
   chatlab/orca/persist/patient.py:
     @persistence_handler
     class PatientInitialPersistence:
         async def persist(response):
             data = PatientInitialOutputSchema.model_validate(response.structured_data)
             # Create Message + Metadata
```

---

**END OF DOCUMENT**
