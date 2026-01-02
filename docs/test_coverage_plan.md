# Comprehensive Test Coverage Plan - Schema Modernization

## Overview

This document defines **complete branch test coverage** for the modernized schema workflow, from definition through API dispatch to parsing and persistence.

**Coverage Goals:**
- ✅ 100% branch coverage for core schema pipeline (SchemaBuilder, FormatBuilder)
- ✅ 95%+ branch coverage for codec encode/decode
- ✅ 90%+ branch coverage for provider integration
- ✅ Integration tests for end-to-end workflows
- ✅ Regression tests for existing functionality
- ✅ Error path coverage for all failure modes

---

## Test Organization

### Directory Structure

```
tests/
├── orchestrai/
│   ├── schemas/
│   │   ├── test_schema_builder.py          # SchemaBuilder unit tests
│   │   ├── test_format_builder.py          # FormatBuilder unit tests
│   │   ├── test_schema_validation.py       # Validation rule tests
│   │   └── test_section_composition.py     # Section registry tests
│   ├── components/
│   │   └── codecs/
│   │       └── openai/
│   │           ├── test_responses_json_codec.py  # Existing, expanded
│   │           └── test_schema_migration.py      # Migration tests
│   ├── providers/
│   │   └── openai/
│   │       ├── test_openai_provider_integration.py  # Existing, expanded
│   │       └── test_request_builder.py              # Request building tests
│   └── integration/
│       ├── test_schema_end_to_end.py        # Full workflow tests
│       ├── test_openai_api_live.py          # Live API tests (optional, gated)
│       └── test_schema_persistence.py       # Persistence integration
└── fixtures/
    ├── schemas/
    │   ├── valid_schemas.py                 # Valid test schemas
    │   ├── invalid_schemas.py               # Invalid test schemas
    │   └── golden_outputs/                  # Golden JSON schema snapshots
    └── responses/
        └── openai_responses.json            # Mock API responses
```

---

## 1. SchemaBuilder Tests

### File: `tests/orchestrai/schemas/test_schema_builder.py`

### Test Cases

#### Valid Schemas

**Test:** `test_simple_object_schema`
- **Input:** `class Simple(BaseModel): name: str`
- **Expected:** `{"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}`
- **Asserts:** Root type, properties, required array

**Test:** `test_nested_object_schema`
- **Input:** Nested model with `Address` inside `Person`
- **Expected:** Nested object with `$defs` or inline properties
- **Asserts:** Nested structure preserved

**Test:** `test_optional_field_schema`
- **Input:** `class Model(BaseModel): opt: str | None = None`
- **Expected:** Field not in `required` array, type allows null
- **Asserts:** Optional fields handled correctly

**Test:** `test_list_field_schema`
- **Input:** `class Model(BaseModel): items: list[str]`
- **Expected:** `{"type": "array", "items": {"type": "string"}}`
- **Asserts:** Array schema correct

**Test:** `test_enum_field_schema`
- **Input:** `class Model(BaseModel): status: Literal["active", "inactive"]`
- **Expected:** `{"type": "string", "enum": ["active", "inactive"]}`
- **Asserts:** Enum values present

**Test:** `test_discriminated_union_nested`
- **Input:** Discriminated union in nested property
- **Expected:** `anyOf` with discriminator in nested field
- **Asserts:** Discriminator present, anyOf preserved

**Test:** `test_complex_nested_union`
- **Input:** `dict[str, Union[str, int, bool]]`
- **Expected:** anyOf in dict value schema
- **Asserts:** Nested union preserved

#### Strict Mode

**Test:** `test_strict_mode_adds_additional_properties_false`
- **Input:** Simple model, `strict=True`
- **Expected:** `"additionalProperties": false`
- **Asserts:** Strict constraint added

**Test:** `test_strict_mode_preserves_explicit_additional_properties`
- **Input:** Model with explicit `additionalProperties: {...}`
- **Expected:** Explicit value preserved
- **Asserts:** No override

**Test:** `test_strict_mode_requires_required_array`
- **Input:** Model with required fields, `strict=True`
- **Expected:** All non-optional fields in `required` array
- **Asserts:** Required array populated

#### Invalid Schemas (Validation Errors)

**Test:** `test_root_type_not_object_raises`
- **Input:** Schema with root `"type": "array"`
- **Expected:** `SchemaValidationError` with message about root type
- **Asserts:** Error raised, clear message

**Test:** `test_root_level_anyof_raises`
- **Input:** Schema with `anyOf` at root
- **Expected:** `SchemaValidationError` with fix suggestion
- **Asserts:** Error raised, suggests container pattern

**Test:** `test_root_level_oneof_raises`
- **Input:** Schema with `oneOf` at root
- **Expected:** `SchemaValidationError`
- **Asserts:** Error raised

**Test:** `test_root_level_allof_raises`
- **Input:** Schema with `allOf` at root (if applicable)
- **Expected:** `SchemaValidationError` or pass (depends on OpenAI support)
- **Asserts:** Consistent behavior

**Test:** `test_missing_properties_raises_in_strict_mode`
- **Input:** Object schema without `properties`, `strict=True`
- **Expected:** `SchemaValidationError`
- **Asserts:** Error raised (if enforced)

#### Edge Cases

**Test:** `test_empty_model`
- **Input:** `class Empty(BaseModel): pass`
- **Expected:** Valid object schema with empty properties
- **Asserts:** No error, valid schema

**Test:** `test_recursive_model`
- **Input:** Self-referential model (e.g., linked list)
- **Expected:** Schema with `$ref` or recursion handling
- **Asserts:** No infinite loop, valid schema

**Test:** `test_forward_reference`
- **Input:** Model with forward reference
- **Expected:** Schema generated after resolution
- **Asserts:** No error

**Test:** `test_generic_model`
- **Input:** Generic model like `Container[T]` (if supported)
- **Expected:** Schema with concrete type
- **Asserts:** Generics resolved

#### Validation = False

**Test:** `test_validation_disabled_allows_invalid_schemas`
- **Input:** Invalid schema (root array), `validate=False`
- **Expected:** Schema returned as-is
- **Asserts:** No error raised

---

## 2. FormatBuilder Tests

### File: `tests/orchestrai/schemas/test_format_builder.py`

### Test Cases

**Test:** `test_openai_responses_format_structure`
- **Input:** Valid schema dict
- **Expected:** `{"format": {"type": "json_schema", "name": "response", "schema": {...}}}`
- **Asserts:** Correct nesting, type, name

**Test:** `test_custom_schema_name`
- **Input:** Schema with `name="custom"`
- **Expected:** `"name": "custom"`
- **Asserts:** Name customizable

**Test:** `test_schema_passed_through_unmodified`
- **Input:** Schema with specific structure
- **Expected:** Inner `schema` field matches input exactly
- **Asserts:** No mutations

**Test:** `test_format_json_serializable`
- **Input:** Schema dict
- **Expected:** Output can be JSON-serialized
- **Asserts:** `json.dumps()` succeeds

---

## 3. Codec Tests (Encode)

### File: `tests/orchestrai/components/codecs/openai/test_responses_json_codec.py`

### Existing Tests (Expanded)

**Test:** `test_encode_with_pydantic_schema_builds_openai_payload`
- **Expand:** Assert SchemaBuilder called, validation run
- **Expand:** Assert FormatBuilder format correct
- **Expand:** Assert `provider_response_format` has correct structure

**Test:** `test_encode_with_raw_schema_dict_and_flatten_unions_applied`
- **UPDATE:** Remove FlattenUnions expectation
- **NEW:** Assert nested unions preserved
- **NEW:** Assert root union rejected (if present)

**Test:** `test_encode_no_schema_is_noop`
- **Existing:** Keep as-is

### New Tests

**Test:** `test_encode_with_nested_union_preserves_anyof`
- **Input:** Schema with nested discriminated union
- **Expected:** `anyOf` present in nested field
- **Asserts:** No flattening

**Test:** `test_encode_with_root_union_raises_error`
- **Input:** Schema with root-level union
- **Expected:** `CodecSchemaError` during encode
- **Asserts:** Error raised before API call

**Test:** `test_encode_strict_mode_applied`
- **Input:** Schema class, strict=True (if configurable)
- **Expected:** `additionalProperties: false` in schema
- **Asserts:** Strict constraints present

**Test:** `test_encode_preserves_discriminator`
- **Input:** Discriminated union schema
- **Expected:** Discriminator field present in JSON schema
- **Asserts:** `discriminator.propertyName` and `mapping` correct

**Test:** `test_encode_schema_identity_attached`
- **Input:** Schema with identity
- **Expected:** Identity information in request metadata
- **Asserts:** Metadata correct

**Test:** `test_encode_multiple_schemas_idempotent`
- **Input:** Same schema class encoded twice
- **Expected:** Identical output both times
- **Asserts:** No side effects, deterministic

---

## 4. Codec Tests (Decode)

### File: `tests/orchestrai/components/codecs/openai/test_responses_json_codec.py`

### Existing Tests (Keep)

- `test_decode_with_schema_returns_pydantic_instance`
- `test_decode_without_schema_returns_raw_dict`
- `test_decode_with_invalid_payload_raises_codecdecodeerror`
- `test_decode_prefers_provider_structured_over_text_json`

### New Tests

**Test:** `test_decode_discriminated_union_resolves_correct_variant`
- **Input:** Response with discriminated union field
- **Expected:** Pydantic resolves to correct variant class
- **Asserts:** Type is specific variant, not base union

**Test:** `test_decode_missing_required_field_raises`
- **Input:** Response missing required field
- **Expected:** `CodecDecodeError` with Pydantic validation error
- **Asserts:** Error details clear

**Test:** `test_decode_extra_field_in_strict_mode_raises`
- **Input:** Response with extra field, strict schema
- **Expected:** `CodecDecodeError` (if Pydantic rejects)
- **Asserts:** Strict mode enforced

**Test:** `test_decode_wrong_type_raises`
- **Input:** Response with `{"age": "not_an_int"}`
- **Expected:** `CodecDecodeError`
- **Asserts:** Type mismatch caught

**Test:** `test_decode_enum_invalid_value_raises`
- **Input:** Response with enum field having invalid value
- **Expected:** `CodecDecodeError`
- **Asserts:** Enum validation enforced

**Test:** `test_decode_nested_object_validates`
- **Input:** Response with nested object
- **Expected:** Nested Pydantic model instance
- **Asserts:** Nested validation works

**Test:** `test_decode_array_of_discriminated_unions`
- **Input:** Response with `list[Union[A, B]]`
- **Expected:** List of correctly typed variant instances
- **Asserts:** All items validated

---

## 5. Provider Integration Tests

### File: `tests/orchestrai/providers/openai/test_openai_provider_integration.py`

### Existing Tests (Expand)

**Test:** `test_healthcheck`
- **Existing:** Keep

**Test:** `test_call_with_structured_output`
- **Expand:** Assert request payload has correct `text.format` structure
- **Expand:** Assert schema in correct format
- **Expand:** Mock API response with structured output
- **Expand:** Assert parsed output typed correctly

### New Tests

**Test:** `test_call_builds_correct_request_payload`
- **Input:** Request with schema
- **Expected:** `text` parameter has format envelope
- **Asserts:** Payload structure matches OpenAI API spec

**Test:** `test_call_with_discriminated_union_schema`
- **Input:** Request with discriminated union schema
- **Expected:** API called with anyOf schema
- **Asserts:** Schema not flattened

**Test:** `test_call_without_schema_omits_text_format`
- **Input:** Request without schema
- **Expected:** `text` parameter absent or empty
- **Asserts:** No schema payload sent

**Test:** `test_call_with_tools_and_schema`
- **Input:** Request with both tools and schema
- **Expected:** Both present in payload
- **Asserts:** No conflicts

**Test:** `test_response_extraction_with_structured_output`
- **Input:** Mock OpenAI response with structured JSON
- **Expected:** Structured output extracted correctly
- **Asserts:** Text extraction works

**Test:** `test_response_extraction_with_reasoning_items`
- **Input:** Response with reasoning items (o1-style)
- **Expected:** Reasoning items filtered out, only content returned
- **Asserts:** Reasoning not in text output

---

## 6. Request Builder Tests

### File: `tests/orchestrai/providers/openai/test_request_builder.py`

**Test:** `test_build_responses_request_minimal`
- **Input:** Request with minimal fields
- **Expected:** Valid payload with model, input
- **Asserts:** JSON-serializable

**Test:** `test_build_responses_request_with_schema`
- **Input:** Request with `provider_response_format`
- **Expected:** `text` parameter contains format envelope
- **Asserts:** Schema nested correctly

**Test:** `test_build_responses_request_with_tools`
- **Input:** Request with tools
- **Expected:** `tools` array present
- **Asserts:** Tool declarations in metadata

**Test:** `test_build_responses_request_metadata_serialization`
- **Input:** Request with codec identity, tools
- **Expected:** `metadata.orchestrai` is JSON string
- **Asserts:** Metadata structure correct

**Test:** `test_build_responses_request_json_safety`
- **Input:** Request with non-JSON-serializable field
- **Expected:** ValueError raised
- **Asserts:** Fails before API call

**Test:** `test_normalize_input_messages`
- **Input:** Various message formats (Pydantic, dict)
- **Expected:** Normalized to OpenAI format
- **Asserts:** role/content extracted

**Test:** `test_extract_tool_declarations`
- **Input:** Tool definitions
- **Expected:** Tool names extracted
- **Asserts:** Duplicates removed, order preserved

---

## 7. Section Composition Tests

### File: `tests/orchestrai/schemas/test_section_composition.py`

**Test:** `test_section_registry_register_and_get`
- **Input:** Register section model
- **Expected:** Model retrievable by name
- **Asserts:** Registry works

**Test:** `test_section_registry_register_handler`
- **Input:** Register section with handler
- **Expected:** Handler retrievable
- **Asserts:** Handler registered

**Test:** `test_composite_schema_with_sections`
- **Input:** Schema with multiple section fields
- **Expected:** Valid schema with nested objects
- **Asserts:** Each section typed correctly

**Test:** `test_optional_section_in_schema`
- **Input:** Schema with optional section field
- **Expected:** Section not in required array
- **Asserts:** Optional handling correct

**Test:** `test_section_extraction_from_parsed_output`
- **Input:** Parsed Pydantic instance with sections
- **Expected:** Each section accessible via field
- **Asserts:** Type safety preserved

**Test:** `test_section_handler_routing`
- **Input:** Parsed output with multiple sections
- **Expected:** Each section routed to correct handler
- **Asserts:** Handler called with correct data

---

## 8. End-to-End Integration Tests

### File: `tests/orchestrai/integration/test_schema_end_to_end.py`

**Test:** `test_full_workflow_simple_schema`
- **Flow:**
  1. Service declares schema
  2. Request built with schema
  3. Codec encodes schema
  4. Provider builds API payload
  5. (Mock) API response received
  6. Codec decodes to Pydantic instance
  7. Assert typed output correct
- **Asserts:** All steps work together

**Test:** `test_full_workflow_discriminated_union`
- **Flow:** Same as above, with discriminated union schema
- **Asserts:** Union variant resolved correctly

**Test:** `test_full_workflow_with_sections`
- **Flow:**
  1. Composite schema with sections
  2. Full encode/decode
  3. Section extraction
  4. Handler routing (mock)
- **Asserts:** Section composition works end-to-end

**Test:** `test_error_handling_invalid_schema`
- **Flow:**
  1. Service declares invalid schema (root union)
  2. Codec encode raises error
  3. Request never sent
- **Asserts:** Error caught early, clear message

**Test:** `test_error_handling_validation_failure`
- **Flow:**
  1. API returns invalid output (missing field)
  2. Codec decode raises error
- **Asserts:** Validation error caught, details preserved

---

## 9. Live API Tests (Optional, Gated)

### File: `tests/orchestrai/integration/test_openai_api_live.py`

**Configuration:**
```python
import pytest
import os

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LIVE_API_TESTS"),
    reason="Live API tests disabled (set RUN_LIVE_API_TESTS=1 to enable)"
)
```

**Test:** `test_live_api_nested_union`
- **Input:** Real schema with nested discriminated union
- **Expected:** API accepts, returns valid output
- **Asserts:** No 400 error, output parses

**Test:** `test_live_api_complex_schema`
- **Input:** Production-like schema (e.g., PatientOutputSchema)
- **Expected:** API accepts, returns valid output
- **Asserts:** All fields present and typed

**Test:** `test_live_api_root_union_rejected`
- **Input:** Schema with root union
- **Expected:** API returns 400 error
- **Asserts:** Error message mentions union/root

---

## 10. Regression Tests

### File: `tests/orchestrai/components/codecs/openai/test_schema_migration.py`

**Test:** `test_existing_patient_initial_schema_still_works`
- **Input:** Existing `PatientInitialOutputSchema`
- **Expected:** Encode/decode works without changes
- **Asserts:** No breaking changes

**Test:** `test_existing_feedback_schema_still_works`
- **Input:** Existing `HotwashInitialSchema`
- **Expected:** Encode/decode works
- **Asserts:** No breaking changes

**Test:** `test_metafield_discriminated_union_still_works`
- **Input:** Existing `MetafieldItem` union
- **Expected:** Union preserved (not flattened)
- **Asserts:** Discriminator present, variants typed

**Test:** `test_backward_compatibility_with_raw_schema_json`
- **Input:** Request with explicit `response_schema_json` dict
- **Expected:** Codec handles correctly
- **Asserts:** Fallback path works

---

## 11. Persistence Integration Tests

### File: `tests/orchestrai/integration/test_schema_persistence.py`

**Test:** `test_persist_section_to_orm`
- **Input:** Parsed section (e.g., PatientDemographics)
- **Expected:** ORM write succeeds
- **Asserts:** Database record created

**Test:** `test_persist_multiple_sections`
- **Input:** Composite output with multiple sections
- **Expected:** Each section persisted to correct table/handler
- **Asserts:** All writes succeed

**Test:** `test_persist_with_idempotency`
- **Input:** Same correlation ID twice
- **Expected:** Second write is idempotent (upsert)
- **Asserts:** No duplicate records

**Test:** `test_persist_validation_failure_rolls_back`
- **Input:** Invalid section data
- **Expected:** Persistence handler rejects, no partial writes
- **Asserts:** Transaction rolled back

---

## 12. Error Path Coverage

### Validation Errors

| Error | Test File | Test Name |
|-------|-----------|-----------|
| Root not object | `test_schema_builder.py` | `test_root_type_not_object_raises` |
| Root-level anyOf | `test_schema_builder.py` | `test_root_level_anyof_raises` |
| Missing properties (strict) | `test_schema_builder.py` | `test_missing_properties_raises_in_strict_mode` |

### Codec Errors

| Error | Test File | Test Name |
|-------|-----------|-----------|
| Invalid schema class | `test_responses_json_codec.py` | `test_encode_with_invalid_schema_raises` |
| Decode validation failure | `test_responses_json_codec.py` | `test_decode_with_invalid_payload_raises_codecdecodeerror` |
| Missing required field | `test_responses_json_codec.py` | `test_decode_missing_required_field_raises` |
| Type mismatch | `test_responses_json_codec.py` | `test_decode_wrong_type_raises` |

### Provider Errors

| Error | Test File | Test Name |
|-------|-----------|-----------|
| API key missing | `test_openai_provider_integration.py` | `test_call_without_api_key_raises` |
| Client not available | `test_openai_provider_integration.py` | `test_call_without_client_raises` |
| API 400 schema error | `test_openai_api_live.py` | `test_live_api_root_union_rejected` |

### Persistence Errors

| Error | Test File | Test Name |
|-------|-----------|-----------|
| Handler not found | `test_schema_persistence.py` | `test_persist_unknown_section_raises` |
| Validation failure | `test_schema_persistence.py` | `test_persist_validation_failure_rolls_back` |
| Database error | `test_schema_persistence.py` | `test_persist_database_error_raises` |

---

## 13. Golden Output Tests

### Concept

Capture "golden" JSON schemas from known-good Pydantic models and assert schema generation produces identical output.

**Location:** `tests/fixtures/schemas/golden_outputs/`

**Example:**
```python
# tests/orchestrai/schemas/test_golden_outputs.py

import json
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent.parent / "fixtures/schemas/golden_outputs"

def test_simple_schema_matches_golden():
    schema = SchemaBuilder.build(SimpleModel)
    golden_path = GOLDEN_DIR / "simple_model.json"

    # First run: write golden
    if not golden_path.exists():
        golden_path.write_text(json.dumps(schema, indent=2))

    # Subsequent runs: compare
    golden = json.loads(golden_path.read_text())
    assert schema == golden, "Schema changed unexpectedly"
```

**Benefits:**
- Detect unintended schema changes
- Easy visual diff review
- Version control for schemas

---

## 14. Coverage Metrics

### Target Coverage by Module

| Module | Target Coverage | Critical Paths |
|--------|----------------|----------------|
| `schemas/builder.py` | 100% | All validation branches |
| `schemas/format_builder.py` | 100% | All format variants |
| `codecs/openai/responses_json.py` | 95% | Encode/decode branches |
| `providers/openai/openai.py` | 90% | Call, extract, adapt |
| `providers/openai/request_builder.py` | 95% | All parameter branches |
| `schemas/registry.py` | 100% | All registry operations |

### Measuring Coverage

```bash
# Run tests with coverage
pytest --cov=orchestrai/schemas --cov=orchestrai/contrib/provider_codecs/openai --cov=orchestrai/contrib/provider_backends/openai --cov-report=html

# View report
open htmlcov/index.html
```

### Coverage Enforcement

Add to CI pipeline:
```yaml
# .github/workflows/test.yml
- name: Run tests with coverage
  run: |
    pytest --cov --cov-fail-under=90
```

---

## 15. Test Execution Strategy

### CI Pipeline Stages

**Stage 1: Fast Unit Tests (< 5 seconds)**
- SchemaBuilder
- FormatBuilder
- Validation rules
- Section registry

**Stage 2: Codec Tests (< 10 seconds)**
- Encode/decode
- Golden outputs
- Error paths

**Stage 3: Provider Integration (< 30 seconds)**
- Mocked API calls
- Request building
- Response parsing

**Stage 4: End-to-End (< 60 seconds)**
- Full workflow with mocks
- Persistence integration (with test DB)

**Stage 5: Live API Tests (optional, manual)**
- Gated by environment variable
- Run on-demand or nightly
- Rate-limited

### Local Development

```bash
# Fast feedback loop (unit tests only)
pytest tests/orchestrai/schemas/ -v

# Full test suite (no live API)
pytest tests/orchestrai/ -v

# With coverage
pytest tests/orchestrai/ --cov --cov-report=term-missing

# Live API tests (if enabled)
RUN_LIVE_API_TESTS=1 pytest tests/orchestrai/integration/test_openai_api_live.py -v
```

---

## 16. Test Maintenance

### Adding New Schemas

When adding a new schema class:
1. Add unit test for schema generation
2. Add golden output snapshot
3. Add encode/decode test
4. Add integration test (if complex)

### Adding New Providers

When adding a new provider:
1. Create provider-specific format builder test
2. Create provider-specific codec tests
3. Create provider integration tests
4. Document provider-specific constraints

### Updating OpenAI API

When OpenAI API changes:
1. Update `openai_schema_notes.md`
2. Add tests for new features
3. Update validation rules if needed
4. Run live API tests to confirm
5. Update golden outputs if schema format changes

---

## 17. Test Data Fixtures

### Shared Fixtures

**File:** `tests/fixtures/schemas/valid_schemas.py`

```python
from pydantic import BaseModel, Field
from typing import Literal, Union, Annotated

class SimpleSchema(BaseModel):
    name: str
    age: int

class NestedSchema(BaseModel):
    person: SimpleSchema
    address: str

class DiscriminatedUnionSchema(BaseModel):
    result: Annotated[
        Union[SuccessResult, ErrorResult],
        Field(discriminator="kind")
    ]

# ... more fixtures
```

**File:** `tests/fixtures/schemas/invalid_schemas.py`

```python
# Root-level union (invalid)
InvalidRootUnion = Union[SimpleSchema, NestedSchema]

# Root array (invalid)
class InvalidRootArray(BaseModel):
    __root__: list[str]  # Not supported

# ... more invalid examples
```

**File:** `tests/fixtures/responses/openai_responses.json`

```json
{
  "simple_success": {
    "id": "resp_123",
    "model": "gpt-4o-mini",
    "output": [
      {
        "type": "message",
        "content": [
          {"type": "output_text", "text": "{\"name\": \"Alice\", \"age\": 30}"}
        ]
      }
    ]
  },
  "discriminated_union_success": {
    "output": [
      {
        "type": "message",
        "content": [
          {"type": "output_text", "text": "{\"result\": {\"kind\": \"success\", \"data\": \"ok\"}}"}
        ]
      }
    ]
  }
}
```

---

## Summary: Test Checklist

### Before Implementation
- [ ] Review all test files in plan
- [ ] Set up fixture directories
- [ ] Configure coverage tools
- [ ] Write golden output capture utility

### During Implementation
- [ ] Write tests FIRST (TDD for SchemaBuilder/FormatBuilder)
- [ ] Achieve 100% branch coverage for new code
- [ ] Add regression tests for existing functionality
- [ ] Update golden outputs as needed

### Before Merge
- [ ] All tests pass locally
- [ ] Coverage thresholds met (90%+)
- [ ] Live API tests pass (if enabled)
- [ ] No decrease in coverage vs. main branch
- [ ] Test execution time < 2 minutes (excluding live API)

### Post-Deploy
- [ ] Monitor error rates in staging
- [ ] Run live API tests against production
- [ ] Verify no parsing errors in logs
- [ ] Check persistence metrics

---

## Appendix: Test Command Reference

```bash
# Run all schema tests
pytest tests/orchestrai/schemas/ -v

# Run codec tests
pytest tests/orchestrai/components/codecs/openai/ -v

# Run provider tests
pytest tests/orchestrai/providers/openai/ -v

# Run integration tests (no live API)
pytest tests/orchestrai/integration/ -v -m "not live_api"

# Run live API tests
RUN_LIVE_API_TESTS=1 pytest tests/orchestrai/integration/test_openai_api_live.py -v

# Run with coverage
pytest --cov=orchestrai --cov-report=html --cov-report=term-missing

# Run specific test
pytest tests/orchestrai/schemas/test_schema_builder.py::test_root_level_anyof_raises -v

# Run in parallel (fast)
pytest -n auto tests/orchestrai/

# Run with verbose output and show print statements
pytest -vv -s tests/orchestrai/schemas/
```
