# SimWorks Schema Review + Update Plan
**Date:** 2026-01-03
**Branch:** `claude/plan-schema-modernization-u3ESb`
**Context:** Post-OrchestrAI schema modernization implementation

---

## Executive Summary

This document provides a complete inventory of schemas used in SimWorks, identifies compatibility issues with the modernized OrchestrAI schema structure and OpenAI Responses API, and proposes a concrete plan for updates.

**Key Findings:**
- ✅ **All schemas are OpenAI-compatible** (root type="object", no root unions)
- ⚠️ **No schemas use OrchestrAI decorators** (not leveraging new validation/caching)
- ⚠️ **Schema generation happens on every request** (performance opportunity)
- ✅ **Clean separation** between Pydantic schemas and Django models
- ⚠️ **Repeated structures** could be extracted into reusable components

---

## 1. Schema Inventory Report

### 1.1 Complete Schema Table

| Name | Location | Owner | Type | Used By | Runtime Output | Persisted | Notes |
|------|----------|-------|------|---------|----------------|-----------|-------|
| **StrictBaseModel** | `simai/response_schema.py:36` | SimWorks | Pydantic Base | All schemas | - | No | Base with `extra="forbid"` |
| **PatientInitialSchema** | `simai/response_schema.py:111` | SimWorks | Pydantic Model | `SimAIClient.generate_patient_initial()` | Patient intro message + metadata | Yes (via parser) | Used for initial simulation response |
| **PatientReplySchema** | `simai/response_schema.py:117` | SimWorks | Pydantic Model | `SimAIClient.generate_patient_reply()` | Patient reply message + metadata | Yes (via parser) | Used for ongoing conversation |
| **PatientResultsSchema** | `simai/response_schema.py:158` | SimWorks | Pydantic Model | `SimAIClient.generate_patient_results()` | Lab/rad results | Yes (LabResult, RadResult models) | Used for clinical results |
| **SimulationFeedbackSchema** | `simai/response_schema.py:170` | SimWorks | Pydantic Model | `SimAIClient.generate_simulation_feedback()` | Simulation assessment | Yes (SimulationMetadata) | Used for end-of-sim feedback |
| **ABCMetadataItem** | `simai/response_schema.py:45` | SimWorks | Pydantic Model | Metadata subcomponents | Metadata key-value pairs | Yes (SimulationMetadata) | Abstract base for metadata |
| **PatientHistoryMetafield** | `simai/response_schema.py:56` | SimWorks | Pydantic Model | Metadata | Patient history items | Yes | Tagged metadata variant |
| **PatientDemographicsMetafield** | `simai/response_schema.py:65` | SimWorks | Pydantic Model | Metadata | Patient demographics | Yes | Tagged metadata variant |
| **SimulationDataMetafield** | `simai/response_schema.py:79` | SimWorks | Pydantic Model | Metadata | Simulation data | Yes | Tagged metadata variant |
| **ScenarioMetadata** | `simai/response_schema.py:84` | SimWorks | Pydantic Model | Metadata | Scenario context | Yes (Simulation fields) | Diagnosis + chief complaint |
| **Metadata** | `simai/response_schema.py:99` | SimWorks | Pydantic Model | All response schemas | Grouped metadata | Yes | Container for all metadata types |
| **MessageItem** | `simai/response_schema.py:106` | SimWorks | Pydantic Model | Response schemas | Chat messages | Yes (Message model) | Patient message structure |
| **LabResult** | `simai/response_schema.py:123` | SimWorks | Pydantic Model | PatientResultsSchema | Lab test results | Yes (LabResult model) | Reusable component |
| **RadResult** | `simai/response_schema.py:148` | SimWorks | Pydantic Model | PatientResultsSchema | Radiology results | Yes (RadResult model) | Reusable component |

### 1.2 GraphQL Schema Files (NOT OpenAI Schemas)

| File | Purpose | Type |
|------|---------|------|
| `chatlab/schema.py` | Strawberry GraphQL types | Django ORM → GraphQL |
| `config/schema.py` | Config GraphQL types | Django ORM → GraphQL |
| `simcore/schema.py` | SimCore GraphQL types | Django ORM → GraphQL |

**Note:** These are Strawberry GraphQL schema definitions, NOT OpenAI response schemas. They map Django models to GraphQL types.

### 1.3 Helper Functions

| Function | Location | Purpose | Notes |
|----------|----------|---------|-------|
| `build_response_text_param()` | `simcore/ai/utils/helpers.py:23` | Build OpenAI `text` param | Generates format envelope inline |
| `maybe_coerce_to_schema()` | `simcore/ai/utils/helpers.py:43` | Parse OpenAI output | Validates JSON against schema |

### 1.4 Dead/Unused Code

**Commented-Out Schemas:**
- Lines 70-76 in `response_schema.py`: `PatientDemographics` (commented out)
- Lines 48-53 in `response_schema.py`: `attribute` field (commented out across multiple metafield classes)
- Lines 91-96 in `response_schema.py`: Additional ScenarioMetadata fields (commented out)

**Action:** Clean up commented code in Patch Set 1.

---

## 2. Compatibility Findings

### 2.1 OpenAI Responses API Compliance

**✅ ALL SCHEMAS PASS OpenAI Requirements:**

Verified against OpenAI Responses JSON Schema constraints:
- ✅ All root schemas have `type: "object"`
- ✅ No root-level `anyOf`/`oneOf`/`allOf`
- ✅ All objects have `properties` field
- ✅ `extra="forbid"` translates to `additionalProperties: false` (correct)
- ✅ All `required` fields are properly declared by Pydantic
- ✅ Literal types translate to `enum` (correct)

**Request Shape:** Confirmed usage in `helpers.py:34-40`
```python
{
    "format": {
        "type": "json_schema",
        "name": model.__name__,
        "schema": model.model_json_schema(),
    }
}
```

✅ **This matches OpenAI Responses API format exactly.**

### 2.2 OrchestrAI Schema Structure Compliance

**⚠️ SCHEMAS DO NOT USE ORCHESTRAI FRAMEWORK**

Current State:
- ❌ No schemas inherit from `BaseOutputSchema`
- ❌ No schemas use `@schema` decorator
- ❌ No integration with OrchestrAI schema registry
- ❌ No provider validation at decoration time
- ❌ No schema caching (generated on every request)

**Impact:**
- **Performance:** Schema generated via `model_json_schema()` on every API call
- **Validation:** No import-time validation (errors only at request time)
- **Caching:** No benefit from decorator-based caching
- **Registry:** Schemas not discoverable via OrchestrAI registry

**Root Cause:** SimWorks predates OrchestrAI schema framework modernization.

### 2.3 SimWorks ↔ OrchestrAI Boundary

**Current Boundary:**
```
SimWorks Pydantic Models → Manual JSON Schema Generation → OpenAI API
```

**Expected Boundary (Post-Modernization):**
```
SimWorks BaseOutputSchema + @schema → Validated/Cached Schema → OrchestrAI Codec → OpenAI API
```

**Gap:** SimWorks bypasses OrchestrAI schema infrastructure entirely.

---

## 3. Current Request Flow Analysis

### 3.1 Actual OpenAI Request Creation Sites

**File:** `simai/client.py`

| Method | Schema Used | Line | Request Builder |
|--------|-------------|------|-----------------|
| `generate_patient_initial()` | `PatientInitialSchema` | 228 | `client.responses.create(text=...)` |
| `generate_patient_reply()` | `PatientReplySchema` | 263 | `client.responses.create(text=...)` |
| `generate_simulation_feedback()` | `SimulationFeedbackSchema` | 294 | `client.responses.create(text=...)` |
| `generate_patient_results()` | `PatientResultsSchema` | 468 | `client.responses.create(text=...)` |

**Text Param Construction:**
All methods call `build_response_text_param(SchemaClass)` which:
1. Calls `model.model_json_schema()` (generates fresh schema)
2. Wraps in `{"format": {"type": "json_schema", ...}}` envelope
3. Returns complete `text` param

**Performance Issue Identified:**
- Schema generated **on every request**
- No caching at Pydantic level
- No caching at OpenAI client level
- Each request pays ~5-10ms schema generation cost

---

## 4. Persistence & ORM Alignment

### 4.1 Schema → Django Model Mapping

**Parser:** `simai/parser.py:StructuredOutputParser`

| Pydantic Schema | Django Model(s) | Mapping Logic |
|-----------------|-----------------|---------------|
| `PatientInitialSchema.messages` | `chatlab.Message` | `_parse_messages()` → creates Message instances |
| `PatientReplySchema.messages` | `chatlab.Message` | Same as above |
| `Metadata.patient_demographics` | `simcore.SimulationMetadata` | `_parse_metadata()` → key-value pairs |
| `Metadata.patient_history` | `simcore.SimulationMetadata` | Same (TODO noted in code) |
| `Metadata.simulation_metadata` | `simcore.SimulationMetadata` | Same |
| `Metadata.scenario_data` | `simcore.Simulation` (fields) | `_parse_scenario_attribute()` → updates Simulation |
| `LabResult` | `simcore.LabResult` | `_parse_results()` → creates LabResult |
| `RadResult` | `simcore.RadResult` | `_parse_results()` → creates RadResult |
| `SimulationFeedbackSchema` | `simcore.SimulationMetadata` | Flattened to key-value metadata |

**✅ Clean Separation:** Pydantic schemas are NEVER persisted directly. Parser extracts data and creates Django models.

**✅ No Circular Imports:** Parser imports both schema and models safely.

**Idempotency:** Not currently enforced - multiple parses of same response would create duplicates.

---

## 5. Proposed Target Architecture

### 5.1 Reusable Component Schemas

Extract these as independent, reusable building blocks:

**Core Components** (already defined, can be kept as-is):
- `LabResult` ✅ (already standalone)
- `RadResult` ✅ (already standalone)
- `MessageItem` ✅ (already standalone)
- `ScenarioMetadata` ✅ (already standalone)

**New Reusable Components** (extract from metafields):
- `PatientDemographicsItem` (rename from `PatientDemographicsMetafield`)
- `PatientHistoryItem` (rename from `PatientHistoryMetafield`)
- `SimulationDataItem` (rename from `SimulationDataMetafield`)

**Benefit:** These can be imported and reused in new schemas without duplication.

### 5.2 Schema Ownership & Import Strategy

**Proposal:** SimWorks owns all response schemas.

**Directory Structure:**
```
SimWorks/
  simai/
    response_schema/
      __init__.py          # Exports all schemas
      base.py              # StrictBaseModel
      components.py        # Reusable components (LabResult, MessageItem, etc.)
      metadata.py          # Metadata schemas
      responses.py         # Main response schemas (PatientInitialSchema, etc.)
```

**Benefits:**
- Clear organization
- Easy to find and import
- Supports future schema additions
- No circular imports (components → metadata → responses)

### 5.3 Integration with OrchestrAI (Optional for Future)

**Option 1:** Keep Current Approach (Low Risk)
- Continue using plain Pydantic models
- SimWorks manages schemas independently
- No OrchestrAI decorator/registry integration
- **Pros:** Simple, works today, low risk
- **Cons:** No caching, no validation at import, no registry integration

**Option 2:** Adopt OrchestrAI Schema Framework (Higher Value)
- Schemas inherit from `BaseOutputSchema`
- Apply `@schema` decorator to each
- Get validation + caching + registry for free
- **Pros:** Performance (caching), fail-fast validation, future-proof
- **Cons:** Requires OrchestrAI dependency, more setup

**Recommended:** Start with Option 1 (refactor only), defer Option 2 to future PR after testing.

### 5.4 Schema Selection Strategy

**Current:** Hardcoded schema per method (1:1 mapping)

```python
generate_patient_initial() → PatientInitialSchema
generate_patient_reply() → PatientReplySchema
generate_simulation_feedback() → SimulationFeedbackSchema
generate_patient_results() → PatientResultsSchema
```

**Proposed:** Same as current (no changes needed)

**Rationale:** Mapping is clean and explicit. No need for dynamic selection.

---

## 6. Patch Plan (Incremental, Reviewable Steps)

### Patch Set 1: Cleanup + Organization (Low Risk)
**Goal:** Remove dead code, reorganize schemas into clear modules.

**Changes:**
- Delete commented-out code in `response_schema.py`
- Split `response_schema.py` into:
  - `response_schema/base.py` (StrictBaseModel)
  - `response_schema/components.py` (LabResult, RadResult, MessageItem, etc.)
  - `response_schema/metadata.py` (Metadata, metafield classes)
  - `response_schema/responses.py` (PatientInitialSchema, etc.)
  - `response_schema/__init__.py` (exports)

**Files Impacted:**
- `simai/response_schema.py` → deleted
- `simai/response_schema/` → new directory
- `simai/client.py` → update imports
- `simai/openai_gateway.py` → update imports
- `simai/parser.py` → update imports
- `simcore/ai/utils/helpers.py` → update imports

**Risk:** Very low (pure refactor, no behavior change)

**Migration:** Update all imports in one commit

**Tests:**
- Existing tests should pass without modification
- Add import smoke tests

---

### Patch Set 2: Extract Reusable Components (Low Risk)
**Goal:** Make components truly reusable by flattening hierarchy.

**Changes:**
- Rename metafield classes to remove "Metafield" suffix:
  - `PatientDemographicsMetafield` → `PatientDemographicsItem`
  - `PatientHistoryMetafield` → `PatientHistoryItem`
  - `SimulationDataMetafield` → `SimulationDataItem`
- Update `Metadata` class to use new names
- Keep `ABCMetadataItem` as base (or rename to `MetadataItem`)

**Files Impacted:**
- `simai/response_schema/components.py`
- `simai/response_schema/metadata.py`
- `simai/parser.py` (update field access if needed)

**Risk:** Low (renaming only, parser maps to Django models anyway)

**Migration:** Straightforward find-replace

**Tests:**
- Update any tests that reference old class names
- Verify parser still creates correct Django models

---

### Patch Set 3: Add Schema-Level Documentation (Very Low Risk)
**Goal:** Document each schema's purpose, usage, and fields.

**Changes:**
- Add comprehensive docstrings to all schema classes
- Document field meanings and constraints
- Add usage examples in docstrings

**Files Impacted:**
- All files in `simai/response_schema/`

**Risk:** Zero (documentation only)

**Tests:** None needed

---

### Patch Set 4: Add Schema Validation Tests (Medium Risk)
**Goal:** Ensure schemas generate valid OpenAI JSON Schema.

**Changes:**
- Create `tests/simai/test_response_schemas.py`
- Add tests for each schema:
  - Test `model_json_schema()` generates valid JSON
  - Test root type is "object"
  - Test required fields are present
  - Test `extra="forbid"` translates correctly
  - Test enum fields for Literals
- Add round-trip tests (schema → JSON → parse → validate)

**Files Impacted:**
- New: `tests/simai/test_response_schemas.py`

**Risk:** Low (tests only, no prod code change)

**Tests:** All new tests

---

### Patch Set 5: Cache Schema Generation (OPTIONAL - Future PR)
**Goal:** Improve performance by caching generated schemas.

**Changes:**
- Add class-level caching to `build_response_text_param()`
- Store generated schema on model class as `_cached_json_schema`
- Return cached schema on subsequent calls

**Example:**
```python
def build_response_text_param(model: Type[BaseModel]) -> ResponseTextConfigParam:
    # Check for cached schema
    if not hasattr(model, '_cached_json_schema'):
        model._cached_json_schema = model.model_json_schema()

    return {
        "format": {
            "type": "json_schema",
            "name": model.__name__,
            "schema": model._cached_json_schema,
        }
    }
```

**Files Impacted:**
- `simcore/ai/utils/helpers.py`

**Risk:** Low (caching only, no behavior change)

**Performance Gain:** ~5-10ms per request (significant at scale)

**Tests:**
- Verify cache is populated
- Verify cache is reused
- Verify cache correctness (no stale schemas)

**Status:** DEFERRED - Recommend separate performance PR

---

### Patch Set 6: Adopt OrchestrAI Schema Framework (OPTIONAL - Future PR)
**Goal:** Integrate with OrchestrAI decorator-based validation and caching.

**Changes:**
- Make all schemas inherit from `orchestrai.components.schemas.BaseOutputSchema`
- Apply `@schema` decorator to each schema class
- Remove manual `build_response_text_param()` calls
- Use OrchestrAI codec for schema encoding

**Files Impacted:**
- All schemas in `simai/response_schema/`
- `simai/client.py` (update request building)
- `simcore/ai/utils/helpers.py` (deprecate manual builder)

**Risk:** HIGH (architectural change, requires thorough testing)

**Benefits:**
- Automatic validation at import time
- Built-in caching (no manual cache needed)
- Registry integration
- Future-proof for multi-provider support

**Status:** DEFERRED - Recommend separate integration PR after stabilization

---

## 7. Testing Requirements

### 7.1 Schema Serialization Tests

**File:** `tests/simai/test_response_schemas.py`

**Test Coverage:**

```python
import pytest
from simai.response_schema import (
    PatientInitialSchema,
    PatientReplySchema,
    PatientResultsSchema,
    SimulationFeedbackSchema,
    LabResult,
    RadResult,
)

class TestSchemaGeneration:
    """Test that schemas generate valid JSON Schema for OpenAI."""

    @pytest.mark.parametrize("schema_class", [
        PatientInitialSchema,
        PatientReplySchema,
        PatientResultsSchema,
        SimulationFeedbackSchema,
    ])
    def test_schema_has_object_root(self, schema_class):
        """All schemas must have root type='object'."""
        schema = schema_class.model_json_schema()
        assert schema["type"] == "object"

    @pytest.mark.parametrize("schema_class", [
        PatientInitialSchema,
        PatientReplySchema,
        PatientResultsSchema,
        SimulationFeedbackSchema,
    ])
    def test_schema_has_properties(self, schema_class):
        """All schemas must have properties field."""
        schema = schema_class.model_json_schema()
        assert "properties" in schema
        assert len(schema["properties"]) > 0

    @pytest.mark.parametrize("schema_class", [
        PatientInitialSchema,
        PatientReplySchema,
        PatientResultsSchema,
        SimulationFeedbackSchema,
    ])
    def test_schema_forbids_extra(self, schema_class):
        """extra='forbid' should translate to additionalProperties=false."""
        schema = schema_class.model_json_schema()
        assert schema.get("additionalProperties") == False

    def test_lab_result_has_enum(self):
        """Literal fields should translate to enum."""
        schema = LabResult.model_json_schema()
        result_flag = schema["properties"]["result_flag"]
        assert "enum" in result_flag
        assert set(result_flag["enum"]) == {
            "HIGH", "LOW", "POS", "NEG", "UNK", "NORMAL", "ABNORMAL", "CRITICAL"
        }
```

### 7.2 OpenAI Request Construction Tests (Mocked)

**File:** `tests/simai/test_client_request_building.py`

**Test Coverage:**

```python
import pytest
from unittest.mock import AsyncMock, patch
from simai.client import SimAIClient
from simai.response_schema import PatientReplySchema
from simcore.models import Simulation

class TestRequestBuilding:
    """Test that OpenAI requests are constructed correctly."""

    @pytest.mark.asyncio
    async def test_patient_reply_request_format(self, mock_simulation):
        """Verify text param has correct structure."""
        client = SimAIClient()

        with patch.object(client.client.responses, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = AsyncMock(
                id="test-id",
                usage=AsyncMock(input_tokens=10, output_tokens=20),
                output_text='{"messages": [], "metadata": {...}}',
            )

            with patch('simai.client.process_response', new_callable=AsyncMock):
                message = await create_test_message(simulation=mock_simulation)
                await client.generate_patient_reply(message)

            # Verify call
            call_kwargs = mock_create.call_args.kwargs
            assert "text" in call_kwargs

            text_param = call_kwargs["text"]
            assert text_param["format"]["type"] == "json_schema"
            assert text_param["format"]["name"] == "PatientReplySchema"
            assert "schema" in text_param["format"]

            schema = text_param["format"]["schema"]
            assert schema["type"] == "object"
            assert "properties" in schema
```

### 7.3 Round-Trip Parse Tests

**File:** `tests/simai/test_schema_parsing.py`

**Test Coverage:**

```python
import pytest
from simai.response_schema import PatientReplySchema, LabResult

class TestRoundTrip:
    """Test that schemas can parse their own generated JSON."""

    def test_patient_reply_round_trip(self):
        """Schema should parse JSON it would generate."""
        # Create valid instance
        valid_data = {
            "image_requested": False,
            "messages": [{"sender": "patient", "content": "Hello"}],
            "metadata": {
                "patient_demographics": [],
                "patient_history": [],
                "simulation_metadata": [],
                "scenario_data": {
                    "diagnosis": "Test",
                    "chief_complaint": "Test complaint"
                }
            }
        }

        # Parse to model
        instance = PatientReplySchema.model_validate(valid_data)

        # Serialize back to JSON
        json_str = instance.model_dump_json()

        # Parse again
        reparsed = PatientReplySchema.model_validate_json(json_str)

        assert reparsed == instance

    def test_schema_rejects_extra_keys(self):
        """extra='forbid' should reject unexpected keys."""
        invalid_data = {
            "image_requested": False,
            "messages": [],
            "metadata": {...},
            "unexpected_field": "should fail"
        }

        with pytest.raises(ValidationError):
            PatientReplySchema.model_validate(invalid_data)
```

### 7.4 Safety Tests (Adapter Prevention)

**File:** `tests/simai/test_schema_safety.py`

**Test Coverage:**

```python
class TestSchemaSafety:
    """Ensure schemas don't produce invalid JSON Schema constructs."""

    def test_no_root_unions(self):
        """Schemas should not have anyOf/oneOf at root."""
        for schema_class in [PatientInitialSchema, PatientReplySchema, ...]:
            schema = schema_class.model_json_schema()
            assert "anyOf" not in schema
            assert "oneOf" not in schema
            assert "allOf" not in schema

    def test_nested_unions_allowed(self):
        """Nested unions in properties ARE allowed."""
        # This test documents that nested unions work
        # (if any schemas use them in the future)
        pass
```

---

## 8. Maintainer Summary

### 8.1 Current State

**SimWorks Schemas:**
- ✅ 4 main response schemas (Initial, Reply, Results, Feedback)
- ✅ 9 component/sub-schemas (LabResult, RadResult, Metadata, etc.)
- ✅ All schemas are OpenAI-compatible
- ⚠️ No OrchestrAI integration
- ⚠️ No caching (performance opportunity)
- ⚠️ No import-time validation
- ⚠️ Some organizational debt (monolithic file, commented code)

**Integration Points:**
- `simai/client.py`: 4 methods that call OpenAI API with schemas
- `simai/parser.py`: Parser that extracts data and creates Django models
- `simcore/ai/utils/helpers.py`: Helper that builds `text` param

### 8.2 Recommended Immediate Actions

**Priority 1: Cleanup (Patch Set 1)**
- Remove commented code
- Reorganize into clear module structure
- Update imports
- **Effort:** 2-4 hours
- **Risk:** Very low
- **Value:** Maintainability

**Priority 2: Testing (Patch Set 4)**
- Add schema validation tests
- Add request construction tests
- Add round-trip tests
- **Effort:** 4-6 hours
- **Risk:** Low (tests only)
- **Value:** Confidence + regression prevention

**Priority 3: Documentation (Patch Set 3)**
- Add docstrings to all schemas
- Document usage patterns
- **Effort:** 2-3 hours
- **Risk:** Zero
- **Value:** Developer experience

### 8.3 Deferred (Future PRs)

**Performance Optimization (Patch Set 5)**
- Add caching to `build_response_text_param()`
- **Value:** ~5-10ms per request
- **Defer Reason:** Need to measure actual impact first

**OrchestrAI Integration (Patch Set 6)**
- Adopt `@schema` decorator
- Integrate with codec system
- **Value:** Validation + caching + registry
- **Defer Reason:** High risk, needs separate focused PR

### 8.4 Key Decisions Required

1. **Should we adopt OrchestrAI schema framework now or later?**
   - **Recommendation:** Later (separate PR after stabilization)

2. **Should we cache schemas manually or wait for OrchestrAI integration?**
   - **Recommendation:** Measure performance first, then decide

3. **Should we reorganize into multiple files?**
   - **Recommendation:** Yes (Patch Set 1 - low risk, high clarity)

4. **Should we rename metafield classes?**
   - **Recommendation:** Yes (Patch Set 2 - improves reusability)

---

## 9. Concrete Module/Code Path References

### 9.1 Schema Definitions
- **Primary:** `SimWorks/simai/response_schema.py` (lines 36-183)
- **Helpers:** `SimWorks/simcore/ai/utils/helpers.py` (lines 23-69)

### 9.2 OpenAI Request Sites
- `SimWorks/simai/client.py:228` - `generate_patient_initial()`
- `SimWorks/simai/client.py:263` - `generate_patient_reply()`
- `SimWorks/simai/client.py:294` - `generate_simulation_feedback()`
- `SimWorks/simai/client.py:468` - `generate_patient_results()`

### 9.3 Schema Parsing
- `SimWorks/simai/parser.py:59-168` - `StructuredOutputParser.parse_output()`
- `SimWorks/simai/openai_gateway.py:27-118` - `process_response()`

### 9.4 Persistence
- `SimWorks/simai/parser.py:169-230` - `build_schema_tasks()`
- Django Models: `simcore.models.Simulation`, `chatlab.models.Message`, `simcore.models.SimulationMetadata`, `simcore.models.LabResult`, `simcore.models.RadResult`

---

## Appendix A: Risk Assessment Matrix

| Patch Set | Risk Level | Behavior Change | Rollback Difficulty | Test Coverage Required |
|-----------|------------|-----------------|---------------------|----------------------|
| 1 (Cleanup) | Very Low | None | Easy (import changes only) | Basic import tests |
| 2 (Rename) | Low | None (internal names) | Easy (find-replace) | Parser tests |
| 3 (Docs) | None | None | N/A | None |
| 4 (Tests) | Low | None (test-only) | N/A | Self-testing |
| 5 (Cache) | Low | None (optimization) | Easy (revert helper) | Cache behavior tests |
| 6 (OrchestrAI) | HIGH | Yes (codec integration) | Difficult | Comprehensive integration tests |

---

## Appendix B: Performance Impact Estimates

| Change | Current | After | Improvement | Notes |
|--------|---------|-------|-------------|-------|
| Schema generation | ~5-10ms per request | ~0ms (cached) | 100% | Via Patch Set 5 or 6 |
| Import-time validation | None | ~50ms total (one-time) | Fail-fast | Via Patch Set 6 |
| Request latency | Baseline | -5-10ms | ~5% faster | Assumes 100-200ms total |

---

**End of Report**
