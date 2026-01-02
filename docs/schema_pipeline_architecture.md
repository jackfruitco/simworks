# Canonical Schema Pipeline Architecture

## Goals

1. **Single source of truth** for schema generation
2. **Minimal, justified transformations** (no over-adaptation)
3. **Clear separation of concerns** (generation → adaptation → format building)
4. **Full type safety** from definition to parsing
5. **Testable at every boundary**
6. **Support for composable section schemas** (per-Lab customization)

---

## Architectural Principles

### 1. No Surprises
- Schema transformations must be explicit, documented, and tested
- No silent field dropping or type mutations
- Fail fast with clear error messages

### 2. Trust OpenAI's Current API
- Nested unions are supported → preserve them
- Root unions are not supported → reject them at design time
- Don't flatten what doesn't need flattening

### 3. Composition Over Monoliths
- Labs should define typed sections: `PatientDemographics`, `LabResults`, etc.
- Top-level schema composes sections
- Each section can have its own persistence handler

### 4. Codec is the Schema Authority
- Services declare schema classes
- Codecs handle generation + adaptation + format building
- Providers receive ready-to-send payloads

---

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ 1. SCHEMA DEFINITION (Lab/Service Author)                   │
│    - Define Pydantic models                                 │
│    - Use composition for sections                           │
│    - Register with @schema decorator                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. SCHEMA GENERATION (SchemaBuilder)                        │
│    - Convert Pydantic → JSON Schema                         │
│    - Validate root structure (must be object)               │
│    - Validate no root-level unions                          │
│    - Ensure strict mode compliance (if requested)           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. SCHEMA ADAPTATION (Optional, Provider-Specific)          │
│    - Apply ONLY necessary transformations                   │
│    - Example: Handle edge cases, strip unsupported keywords │
│    - NO FLATTENING of nested unions                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. FORMAT BUILDING (FormatBuilder)                          │
│    - Wrap schema in provider's required envelope            │
│    - OpenAI: {"format": {"type": "json_schema", ...}}       │
│    - Other providers: different wrappers                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. REQUEST BUILDING (Provider Backend)                      │
│    - Attach format to correct API parameter                 │
│    - OpenAI: text={...}                                     │
│    - Serialize to JSON                                      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. API CALL (Provider)                                      │
│    - Execute request                                        │
│    - Receive response                                       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. RESPONSE PARSING (Codec)                                 │
│    - Extract structured output candidate                    │
│    - Validate against original schema                       │
│    - Return typed Pydantic instance                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 8. PERSISTENCE (Section Handlers)                           │
│    - Split composite output by section                      │
│    - Route each section to appropriate handler              │
│    - Handle idempotency, validation, ORM writes             │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. SchemaBuilder

**Responsibility:** Generate clean, valid JSON Schema from Pydantic models

**Location:** `packages/orchestrai/src/orchestrai/schemas/builder.py` (new)

**Interface:**
```python
class SchemaBuilder:
    """Build OpenAI-compatible JSON Schema from Pydantic models."""

    @staticmethod
    def build(
        model: type[BaseModel],
        *,
        strict: bool = True,
        validate: bool = True,
    ) -> dict[str, Any]:
        """
        Build JSON Schema from Pydantic model.

        Args:
            model: Pydantic model class
            strict: Apply strict mode constraints (additionalProperties, etc.)
            validate: Validate schema structure for OpenAI compatibility

        Returns:
            JSON Schema dict

        Raises:
            SchemaValidationError: If schema violates OpenAI constraints
        """
        pass
```

**Implementation Steps:**
1. Call `model.model_json_schema()`
2. If `validate=True`, run validation checks:
   - Root must be `{"type": "object"}`
   - Root must not have `anyOf`/`oneOf`/`allOf`
   - If strict, ensure `additionalProperties` handled
   - Ensure `properties` is present
3. If `strict=True`, apply strict mode constraints:
   - Set `additionalProperties: false` if not specified
   - Ensure all required fields are in `required` array
4. Return clean schema

**Validation Errors:**
```python
class SchemaValidationError(Exception):
    """Schema violates provider constraints."""
    pass

# Example errors:
# - "Root schema must have type 'object', got 'array'"
# - "Root-level unions (anyOf/oneOf) are not supported. Wrap in container object."
# - "Strict mode requires 'required' array to be present"
```

---

### 2. SchemaAdapter (Minimal)

**Responsibility:** Apply ONLY necessary provider-specific transformations

**Current State:** `FlattenUnions` over-adapts

**Proposed State:** Remove or drastically simplify

**Option A: Remove Entirely**
- If all schemas can be designed without root unions, no adapter needed
- Validation in SchemaBuilder catches design errors
- Cleaner, more predictable

**Option B: Minimal Root-Level Union Handler**
- Only flatten IF root has `anyOf`/`oneOf` (rare, should be design error)
- Preserve all nested unions
- Log warning when flattening happens

**Recommended:** **Option A** - remove adapter, enforce good schema design

**If keeping adapter:**
```python
class MinimalOpenAIAdapter(BaseSchemaAdapter):
    """Handle edge cases for OpenAI schema compatibility."""

    order = 0

    def adapt(self, schema: dict[str, Any]) -> dict[str, Any]:
        """
        Apply minimal transformations for OpenAI compatibility.

        Currently: NO-OP (all validation done in SchemaBuilder)

        Future: Add only if specific edge cases discovered.
        """
        # Option: strip unsupported keywords (if any discovered)
        # Option: normalize specific patterns (if needed)
        return schema  # Pass-through for now
```

---

### 3. FormatBuilder

**Responsibility:** Wrap schema in provider-specific envelope

**Location:** `packages/orchestrai/src/orchestrai/schemas/format_builder.py` (new)

**Interface:**
```python
class FormatBuilder:
    """Build provider-specific format envelopes."""

    @staticmethod
    def build_openai_responses_format(
        schema: dict[str, Any],
        *,
        name: str = "response",
    ) -> dict[str, Any]:
        """
        Wrap schema in OpenAI Responses API format.

        Args:
            schema: Valid JSON Schema dict
            name: Schema name (default: "response")

        Returns:
            Format envelope ready for text.format parameter
        """
        return {
            "format": {
                "type": "json_schema",
                "name": name,
                "schema": schema,
            }
        }
```

**Usage:**
```python
schema = SchemaBuilder.build(MyModel)
format_envelope = FormatBuilder.build_openai_responses_format(schema)
# Attach to request.text parameter
```

---

### 4. Codec Integration

**Updated Codec Flow:**

**File:** `packages/orchestrai/src/orchestrai/contrib/provider_codecs/openai/responses_json.py`

**Method:** `aencode()`

**New Implementation:**
```python
from orchestrai.schemas.builder import SchemaBuilder
from orchestrai.schemas.format_builder import FormatBuilder

async def aencode(self, req: Request) -> None:
    """Attach OpenAI Responses format to request."""

    # 1. Get Pydantic model
    schema_cls = getattr(req, "response_schema", None)
    if schema_cls is None:
        return  # No structured output

    # 2. Build clean schema (with validation)
    try:
        schema = SchemaBuilder.build(schema_cls, strict=True, validate=True)
    except SchemaValidationError as exc:
        raise CodecSchemaError(f"Invalid schema for {schema_cls}: {exc}") from exc

    # 3. Build format envelope
    format_envelope = FormatBuilder.build_openai_responses_format(schema)

    # 4. Attach to request
    req.response_schema_json = schema  # For diagnostics
    setattr(req, "provider_response_format", format_envelope)
```

**Benefits:**
- Clear separation: build → format → attach
- No hidden transformations
- Validation happens early
- Easy to test each step

---

## Composable Section Schemas

### Problem Statement

Labs want to define structured outputs with typed sections:
- `PatientDemographics`
- `LabResults`
- `ScenarioMetadata`
- `Messages`

Each section should:
- Have its own Pydantic type
- Be extractable from parsed output
- Route to section-specific persistence handler
- Support optional sections (some labs don't need all sections)

### Proposed Solution: Schema Composition Pattern

**1. Define Section Models**

```python
# SimWorks/common/schemas/sections.py

class PatientDemographics(BaseModel):
    """Patient demographic information."""
    age: int
    gender: str
    name: str

class LabResult(BaseModel):
    """Single lab test result."""
    test_name: str
    value: float
    unit: str
    reference_range: str
    flag: Literal["normal", "abnormal"]

class LabResults(BaseModel):
    """Collection of lab results."""
    results: list[LabResult]
```

**2. Compose Top-Level Schema**

```python
# SimWorks/chatlab/orca/schemas/patient.py

from common.schemas.sections import PatientDemographics, LabResults
from orchestrai_django.components.schemas import DjangoBaseOutputSchema

@schema
class PatientOutputSchema(DjangoBaseOutputSchema):
    """Composite patient output with typed sections."""

    # Core sections
    patient: PatientDemographics
    labs: LabResults | None = None  # Optional

    # Messages
    messages: list[DjangoOutputItem]

    # Metadata
    llm_conditions_check: list[LLMConditionsCheckItem]
```

**3. Section Registry (Optional)**

For labs that need dynamic section registration:

```python
# orchestrai_django/schemas/registry.py

class SectionRegistry:
    """Registry for schema section types and persistence handlers."""

    _sections: dict[str, type[BaseModel]] = {}
    _handlers: dict[str, Callable] = {}

    @classmethod
    def register_section(
        cls,
        name: str,
        model: type[BaseModel],
        handler: Callable | None = None,
    ) -> None:
        """Register a schema section type."""
        cls._sections[name] = model
        if handler:
            cls._handlers[name] = handler

    @classmethod
    def get_section_model(cls, name: str) -> type[BaseModel] | None:
        """Get section model by name."""
        return cls._sections.get(name)

    @classmethod
    def get_handler(cls, name: str) -> Callable | None:
        """Get persistence handler for section."""
        return cls._handlers.get(name)
```

**Usage:**
```python
# In lab initialization:
SectionRegistry.register_section(
    "patient_demographics",
    PatientDemographics,
    handler=persist_patient_demographics,
)

SectionRegistry.register_section(
    "lab_results",
    LabResults,
    handler=persist_lab_results,
)
```

**4. Persistence Integration**

```python
# After parsing response:
output: PatientOutputSchema = codec.decode(response)

# Route sections to handlers
if output.patient:
    await persist_patient_demographics(output.patient, context)

if output.labs:
    await persist_lab_results(output.labs, context)

# Or use registry:
for section_name in ["patient", "labs"]:
    section_data = getattr(output, section_name, None)
    if section_data:
        handler = SectionRegistry.get_handler(section_name)
        if handler:
            await handler(section_data, context)
```

**Benefits:**
- Type-safe section extraction
- Clear field-to-handler mapping
- Optional sections supported naturally
- Each section model is reusable across schemas
- Persistence logic is decoupled and testable

---

## Migration Path

### Phase 1: New Pipeline (Parallel to Existing)

**Steps:**
1. Create `orchestrai/schemas/builder.py` with `SchemaBuilder`
2. Create `orchestrai/schemas/format_builder.py` with `FormatBuilder`
3. Add comprehensive tests for both
4. **Do not modify existing codec yet**

**Tests:**
- SchemaBuilder: valid schemas, invalid schemas, strict mode
- FormatBuilder: correct envelope structure

### Phase 2: Update One Codec

**Steps:**
1. Update `OpenAIResponsesJsonCodec.aencode()` to use new pipeline
2. Remove `FlattenUnions` and `OpenaiWrapper` from adapter list
3. Run existing codec tests (should pass)
4. Add new tests for edge cases

**Validation:**
- All existing tests pass
- New validation errors are clear and actionable

### Phase 3: Deploy Section Composition (Opt-In)

**Steps:**
1. Create common section models (PatientDemographics, etc.)
2. Update ONE schema to use composition pattern
3. Update ONE service to parse sections
4. Add persistence handlers for sections
5. Test end-to-end with real API

**Target:** PatientInitialOutputSchema as pilot

### Phase 4: Migrate Remaining Schemas

**Steps:**
1. Audit all existing schemas
2. Identify root-level unions (if any) → redesign as container objects
3. Migrate to composition pattern where beneficial
4. Update services to extract sections
5. Expand persistence handlers

### Phase 5: Remove Legacy Adapters

**Steps:**
1. Verify no schemas use root-level unions
2. Remove `FlattenUnions` class
3. Remove `OpenaiWrapper` class (logic moved to FormatBuilder)
4. Update documentation
5. Delete dead code

---

## Error Handling Strategy

### Schema Validation Errors (Design Time)

**Where:** `SchemaBuilder.build()` with `validate=True`

**Examples:**
```python
# Error 1: Root is not object
SchemaValidationError(
    "Root schema must have type 'object', got 'array'. "
    "Wrap your array in an object with a field."
)

# Error 2: Root-level union
SchemaValidationError(
    "Root-level unions (anyOf/oneOf) are not supported by OpenAI. "
    "Redesign your schema to use a discriminated union in a nested field. "
    "Example: class Container(BaseModel): item: Union[A, B]"
)

# Error 3: Missing required in strict mode
SchemaValidationError(
    "Strict mode enabled but 'required' field is missing. "
    "Ensure all mandatory fields are listed in 'required' array."
)
```

**Response:** Fail during encode (before API call)

### API Schema Rejection (Runtime)

**Where:** OpenAI API returns 400 with schema error

**Examples:**
```
HTTP 400: Invalid schema: additionalProperties must be false or object
HTTP 400: Invalid schema: root type must be object
HTTP 400: Invalid schema: anyOf not supported at root level
```

**Response:** Wrap in `ProviderError`, log original error, fail request

### Parsing Errors (Response)

**Where:** `Codec.adecode()` → Pydantic validation

**Examples:**
```python
# Field type mismatch
ValidationError: field 'age' expected int, got str

# Missing required field
ValidationError: field 'name' is required

# Discriminator mismatch
ValidationError: discriminator 'kind' value 'unknown' does not match any variant
```

**Response:** Wrap in `CodecDecodeError`, preserve validation details

---

## Testing Strategy

### Unit Tests

**SchemaBuilder:**
- ✅ Valid object schema
- ✅ Valid nested object
- ✅ Valid array of objects
- ✅ Valid discriminated union (nested)
- ❌ Invalid root type (array, string, etc.)
- ❌ Invalid root-level union
- ✅ Strict mode adds constraints
- ✅ Pydantic optional fields handled

**FormatBuilder:**
- ✅ Correct envelope structure
- ✅ Custom schema name
- ✅ Schema passed through unmodified

**Codec Encode:**
- ✅ Pydantic model → schema → format → request
- ✅ No schema → no-op
- ❌ Invalid schema → CodecSchemaError

**Codec Decode:**
- ✅ Valid JSON → Pydantic instance
- ✅ No schema → raw dict
- ❌ Invalid JSON → CodecDecodeError
- ❌ Validation failure → CodecDecodeError

### Integration Tests

**End-to-End:**
1. Service declares schema
2. Codec encodes schema
3. Provider builds request
4. (Mock) API call succeeds
5. Provider receives response
6. Codec decodes to Pydantic instance
7. Assertions on typed fields

**With Real API (Optional):**
- One test with minimal schema
- One test with complex nested schema
- One test with discriminated union
- Verify parsed output matches expected types

### Regression Tests

**Existing Functionality:**
- All current schemas continue to work
- All current services continue to parse outputs
- No breaking changes to public APIs

---

## Documentation Requirements

### For Lab Authors

**Guide:** "Designing Output Schemas for SimWorks"

**Topics:**
1. Basic schema structure (must be object at root)
2. Nested unions are OK (with examples)
3. Root unions are NOT OK (how to fix)
4. Using composition for sections
5. Registering section handlers
6. Common patterns and examples

### For Schema Developers

**Guide:** "Schema Pipeline Internals"

**Topics:**
1. SchemaBuilder implementation
2. Validation rules
3. FormatBuilder envelopes
4. Adding new providers
5. Debugging schema issues

### Migration Guide

**Guide:** "Migrating from FlattenUnions to New Pipeline"

**Topics:**
1. Why the change
2. What's different
3. How to update schemas
4. How to test
5. Rollback plan

---

## Success Criteria

### Functional
- ✅ All existing schemas work without modification OR clear migration path provided
- ✅ New schemas can use nested unions without issues
- ✅ Root-level union designs caught at encode time with helpful error
- ✅ Section composition pattern works end-to-end
- ✅ Persistence handlers can be registered and routed

### Quality
- ✅ 100% branch coverage for SchemaBuilder
- ✅ 100% branch coverage for FormatBuilder
- ✅ 90%+ coverage for codec encode/decode
- ✅ At least 2 integration tests (mock + optional live API)
- ✅ Clear error messages for all failure modes

### Performance
- ✅ Schema generation time < 10ms for typical schemas
- ✅ No measurable latency increase in request build
- ✅ Codec encode/decode performance unchanged or improved

### Maintainability
- ✅ Dead code removed (FlattenUnions if obsolete)
- ✅ Clear module boundaries
- ✅ Comprehensive inline documentation
- ✅ Migration guide written and tested

---

## Open Questions

### 1. Should SchemaBuilder cache schemas?
**Consideration:** Same Pydantic model generates same schema
**Trade-off:** Memory vs compute
**Recommendation:** Add optional cache with TTL, default disabled

### 2. How to handle schema evolution?
**Consideration:** Lab updates schema, old data persists
**Trade-off:** Strict validation vs flexibility
**Recommendation:** Version schemas via identity, handle migrations explicitly

### 3. Should we support multiple providers with different constraints?
**Consideration:** Anthropic, local models, etc. may have different rules
**Trade-off:** Generic pipeline vs provider-specific builders
**Recommendation:** Abstract validation rules into provider-specific validators

### 4. How to handle very large schemas?
**Consideration:** Token limits, complexity limits
**Trade-off:** Splitting schemas vs monolithic
**Recommendation:** Add schema size validator, warn above threshold

---

## Timeline Estimate (Implementation)

**NOTE:** This is a PLAN document. No code changes yet.

**Estimated Effort:** 15-20 developer-days

**Breakdown:**
- SchemaBuilder + tests: 3 days
- FormatBuilder + tests: 1 day
- Codec migration + tests: 3 days
- Section composition framework: 2 days
- Documentation: 2 days
- Integration tests: 2 days
- Migration of existing schemas: 3-5 days
- Buffer for issues: 2 days

**Phases:**
- Phase 1-2: 1 week (new pipeline + codec update)
- Phase 3: 3-5 days (section composition pilot)
- Phase 4: 1 week (migrate remaining schemas)
- Phase 5: 1 day (cleanup)

**Critical Path:** Codec migration → Section composition → Schema migration
