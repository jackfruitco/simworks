# Schema Modernization Implementation Plan v2

**Status:** PLAN & REVIEW - No code changes yet
**Branch:** `orchestrai_v0.4.0`
**Estimated Effort:** 8-12 developer-days (2-3 weeks)

---

## Executive Summary

This plan modernizes the structured-output schema workflow to:

1. ✅ **Align with current OpenAI Responses API** (nested unions supported, root unions not)
2. ✅ **Remove FlattenUnions adapter** (obsolete - nested unions work now)
3. ✅ **Validate schemas at decoration time** (fail at import, not runtime)
4. ✅ **Tag schemas with provider compatibility** (metadata-driven)
5. ✅ **Enable composable schemas** (per-Lab section types)
6. ✅ **Improve testability** (validate/adapt/encode independently)

**Key Architecture Decision:** Use decorator-based validation with provider compatibility tagging (no SchemaBuilder class needed).

---

## Updated Architecture

### Core Concept: Validate in Decorator, Adapt in Codec

```
┌─────────────────────────────────────────────────────────────┐
│ 1. SCHEMA DEFINITION (Lab Author)                           │
│    @schema                                                   │
│    class PatientSchema(BaseModel):                          │
│        patient: PatientDemographics                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. DECORATION TIME (Import/Startup)                         │
│    - Generate JSON Schema (Pydantic)                        │
│    - Run provider validators (OpenAI rules)                 │
│    - Tag with compatibility metadata                        │
│    - Cache validated schema                                 │
│    - Register in component store                            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. REQUEST TIME (Service Call)                              │
│    - Codec checks compatibility tag                         │
│    - Uses cached validated schema                           │
│    - Applies format adapter (wraps in OpenAI envelope)      │
│    - Attaches to request                                    │
└─────────────────────────────────────────────────────────────┘
```

---

## File Structure

### New Files

```
packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/schema/
├── __init__.py
├── validate.py          # OpenAI validation rules
└── adapt.py             # OpenAI format adapter (moved/renamed from schema_adapters.py)
```

### Modified Files

```
packages/orchestrai_django/src/orchestrai_django/decorators/schema.py
  - Add validation during decoration
  - Tag schemas with compatibility metadata
  - Cache validated schemas

packages/orchestrai/src/orchestrai/contrib/provider_codecs/openai/responses_json.py
  - Check schema compatibility
  - Use cached validated schema
  - Call _apply_adapters helper
```

### Deleted Files

```
packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/schema_adapters.py
  - FlattenUnions class (obsolete)
  - OpenaiWrapper class (moved to adapt.py)
```

---

## Implementation Details

### 1. OpenAI Validators

**File:** `packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/schema/validate.py`

```python
"""OpenAI Responses API schema validation rules."""

from typing import Callable, Tuple

# Type alias for validator functions
# Returns: (is_valid: bool, error_message: str)
ValidatorFunc = Callable[[dict, str], Tuple[bool, str]]


def _root_is_object(schema: dict, name: str) -> Tuple[bool, str]:
    """Validate root schema is type 'object'."""
    schema_type = schema.get("type")
    if schema_type != "object":
        return (
            False,
            f"{name}: Root schema must be type 'object', got '{schema_type}'. "
            f"OpenAI Responses API requires an object at the root level."
        )
    return True, ""


def _no_root_unions(schema: dict, name: str) -> Tuple[bool, str]:
    """Validate no anyOf/oneOf at root level."""
    if "anyOf" in schema:
        return (
            False,
            f"{name}: Root-level 'anyOf' unions are not supported by OpenAI. "
            f"Nested unions ARE supported. Redesign with discriminated union in a field:\n"
            f"  class {name}(BaseModel):\n"
            f"      item: Annotated[Union[A, B], Field(discriminator='kind')]"
        )

    if "oneOf" in schema:
        return (
            False,
            f"{name}: Root-level 'oneOf' unions are not supported by OpenAI. "
            f"Nested unions ARE supported. Redesign with discriminated union in a field."
        )

    return True, ""


def _has_properties(schema: dict, name: str) -> Tuple[bool, str]:
    """Validate schema has properties field."""
    if "properties" not in schema:
        return (
            False,
            f"{name}: Root schema must have 'properties' field. "
            f"Define at least one field in your Pydantic model."
        )
    return True, ""


# Registry of OpenAI validation rules
OPENAI_VALIDATORS: dict[str, ValidatorFunc] = {
    "root_is_object": _root_is_object,
    "no_root_unions": _no_root_unions,
    "has_properties": _has_properties,
}


def validate_openai_schema(schema: dict, name: str, *, strict: bool = True) -> bool:
    """Validate schema meets OpenAI Responses API requirements.

    Args:
        schema: JSON Schema dict
        name: Schema name for error messages
        strict: If True, raise ValueError on validation failure.
                If False, return bool without raising.

    Returns:
        True if schema is compatible, False otherwise (only if strict=False)

    Raises:
        ValueError: If schema is incompatible and strict=True
    """
    for validator_name, validator_func in OPENAI_VALIDATORS.items():
        is_valid, error_msg = validator_func(schema, name)
        if not is_valid:
            if strict:
                raise ValueError(error_msg)
            return False

    return True
```

---

### 2. OpenAI Format Adapter

**File:** `packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/schema/adapt.py`

```python
"""OpenAI Responses API schema adapters."""

from typing import Any, Dict
from orchestrai.components.schemas.adapters import BaseSchemaAdapter


class OpenaiBaseSchemaAdapter(BaseSchemaAdapter):
    """Base class for OpenAI-specific schema adapters."""
    provider_slug = "openai-prod"


class OpenaiFormatAdapter(OpenaiBaseSchemaAdapter):
    """Adapt generic JSON Schema into OpenAI Responses API format envelope.

    Transforms a validated JSON Schema into the OpenAI-specific structure
    required by the Responses API's text.format parameter.

    Input:  {"type": "object", "properties": {...}}
    Output: {"format": {"type": "json_schema", "name": "response", "schema": {...}}}

    This is a real adaptation - converting from generic JSON Schema to
    provider-specific envelope format.

    Order: 999 (runs last, after any other transformations)
    """
    order = 999

    def adapt(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Wrap schema in OpenAI Responses API format envelope."""
        return {
            "format": {
                "type": "json_schema",
                "name": "response",
                "schema": schema,
            }
        }


# Export for backward compatibility
__all__ = ["OpenaiBaseSchemaAdapter", "OpenaiFormatAdapter"]
```

---

### 3. Schema Decorator with Validation

**File:** `packages/orchestrai_django/src/orchestrai_django/decorators/schema.py`

```python
"""Schema decorator with provider validation."""

from orchestrai.contrib.provider_backends.openai.schema.validate import (
    validate_openai_schema
)


# Provider validation configuration
PROVIDER_VALIDATION_CONFIG = {
    "openai": {
        "enabled": True,   # Run validation by default
        "strict": True,    # Fail on validation error
        "validator": validate_openai_schema,
    },
    # Future providers can be added here:
    # "anthropic": {
    #     "enabled": False,
    #     "strict": False,
    #     "validator": validate_anthropic_schema,
    # },
}


def schema(cls):
    """Register and validate output schema.

    This decorator:
    1. Generates JSON Schema from Pydantic model
    2. Validates schema against enabled providers
    3. Tags schema with provider compatibility metadata
    4. Caches validated schema for performance
    5. Registers schema in component store

    Raises:
        ValueError: If schema fails validation (when strict=True)
    """
    # Generate JSON Schema
    schema_json = cls.model_json_schema()

    # Run provider validations
    compatibility = {}

    for provider, config in PROVIDER_VALIDATION_CONFIG.items():
        if not config["enabled"]:
            continue

        validator = config["validator"]
        strict = config["strict"]

        try:
            is_compatible = validator(schema_json, cls.__name__, strict=strict)
            compatibility[provider] = is_compatible
        except ValueError:
            # Validation failed and strict=True raised error
            compatibility[provider] = False
            raise  # Re-raise for fail-fast behavior

    # Tag schema with metadata
    cls._provider_compatibility = compatibility
    cls._validated_schema = schema_json
    cls._validated_at = "decoration"

    # Cache for performance (avoid regenerating schema)
    cls._cached_openai_schema = schema_json

    # Register in component store (existing logic)
    register_component(cls)

    return cls
```

---

### 4. Updated Codec

**File:** `packages/orchestrai/src/orchestrai/contrib/provider_codecs/openai/responses_json.py`

```python
"""OpenAI Responses JSON codec."""

import logging
from typing import Any, ClassVar, Sequence

from pydantic import ValidationError

from orchestrai.contrib.provider_backends.openai.schema.adapt import OpenaiFormatAdapter
from orchestrai.components.codecs import BaseCodec
from orchestrai.components.codecs.exceptions import CodecDecodeError, CodecSchemaError
from orchestrai.components.schemas import BaseSchemaAdapter
from orchestrai.decorators import codec
from orchestrai.tracing import service_span_sync
from orchestrai.types import Request, Response

logger = logging.getLogger(__name__)


@codec(name="json")
class OpenAIResponsesJsonCodec(BaseCodec):
    """Codec for OpenAI Responses JSON structured output.

    Encode:
      - Checks schema was validated for OpenAI (during decoration)
      - Uses cached validated schema
      - Applies format adapter (wraps in OpenAI envelope)
      - Attaches to request.provider_response_format

    Decode:
      - Extracts structured output from response
      - Validates into original Pydantic schema
      - Returns typed model instance
    """

    # Format adapter (wraps schema in OpenAI envelope)
    schema_adapters: ClassVar[Sequence[BaseSchemaAdapter]] = (
        OpenaiFormatAdapter(order=999),
    )

    async def aencode(self, req: Request) -> None:
        """Attach OpenAI Responses format to request.

        Assumes schema was already validated during @schema decoration.
        Uses cached validated schema for performance.
        """
        with service_span_sync(
            "orchestrai.codec.encode",
            attributes={
                "orchestrai.codec": self.__class__.__name__,
                "orchestrai.provider_name": "openai",
            },
        ):
            schema_cls = getattr(req, "response_schema", None)
            if schema_cls is None:
                return  # No structured output requested

            # Check schema was validated for OpenAI
            compatibility = getattr(schema_cls, "_provider_compatibility", {})
            if not compatibility.get("openai"):
                raise CodecSchemaError(
                    f"Schema {schema_cls.__name__} not validated for OpenAI. "
                    f"Ensure @schema decorator is applied and validation passed."
                )

            # Use cached validated schema (avoid regenerating)
            schema = getattr(
                schema_cls,
                "_validated_schema",
                schema_cls.model_json_schema()  # Fallback if not cached
            )

            # Apply format adapter (wraps in OpenAI envelope)
            adapted_schema = self._apply_adapters(schema)

            # Attach to request
            req.response_schema_json = schema  # Original for diagnostics
            setattr(req, "provider_response_format", adapted_schema)

    def _apply_adapters(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Apply schema adapters in order.

        Args:
            schema: Validated JSON Schema dict

        Returns:
            Adapted schema (wrapped in provider format)
        """
        result = schema
        for adapter in sorted(self.schema_adapters, key=lambda a: a.order):
            result = adapter.adapt(result)
        return result

    async def adecode(self, resp: Response) -> Any | None:
        """Decode structured output from Response into Pydantic model.

        Extracts JSON from response, validates into original schema.
        """
        with service_span_sync(
            "orchestrai.codec.decode",
            attributes={
                "orchestrai.codec": self.__class__.__name__,
                "orchestrai.provider_name": "openai",
            },
        ):
            # Extract structured output candidate
            candidate = self.extract_structured_candidate(resp)
            if candidate is None:
                return None

            # Get original schema class
            schema_cls = None
            req = getattr(resp, "request", None)
            if req is not None:
                schema_cls = getattr(req, "response_schema", None)

            # Fallback to service's schema if request schema not available
            if schema_cls is None:
                schema_cls = self._get_schema_from_service()

            # Fallback to codec's class-level schema
            if schema_cls is None:
                schema_cls = self.response_schema

            # No schema: return raw dict
            if schema_cls is None:
                return candidate

            # Validate into Pydantic model
            try:
                if hasattr(schema_cls, "model_validate"):
                    return schema_cls.model_validate(candidate)
                return schema_cls(**candidate)
            except ValidationError as exc:
                raise CodecDecodeError(
                    f"Structured output validation failed for {schema_cls.__name__}"
                ) from exc
            except Exception as exc:
                raise CodecDecodeError(
                    f"Unexpected error during decode: {exc}"
                ) from exc
```

---

## What Changes

### ✅ Add

1. **`openai/schema/validate.py`** - Validation rules
2. **`openai/schema/adapt.py`** - Format adapter (moved)
3. **`openai/schema/__init__.py`** - Package init
4. **Validation in `@schema` decorator** - Run validators at decoration
5. **Compatibility tagging** - `_provider_compatibility` metadata
6. **Schema caching** - `_validated_schema` attribute

### ❌ Remove

1. **`FlattenUnions` adapter** - Obsolete (nested unions work)
2. **`openai/schema_adapters.py`** - Split into validate.py + adapt.py

### 🔄 Modify

1. **`@schema` decorator** - Add validation + tagging
2. **Codec encode** - Check compatibility, use cached schema
3. **Codec decode** - No changes (already works)

---

## Implementation Phases

### Phase 1: Add Validation Infrastructure (2-3 days)
**Risk:** Low (new code, parallel to existing)

**Tasks:**
1. Create `openai/schema/validate.py` with validators
2. Create `openai/schema/adapt.py` with format adapter
3. Write comprehensive tests for validators
4. Write tests for format adapter

**Deliverables:**
- [ ] `validate.py` with 3+ validation rules
- [ ] `adapt.py` with format adapter
- [ ] 15+ tests for validators (valid/invalid cases)
- [ ] 5+ tests for format adapter
- [ ] 100% coverage for new modules

**Validation:**
- All tests pass
- No changes to existing code yet
- Validators can be called independently

---

### Phase 2: Update Schema Decorator (2 days)
**Risk:** Medium (modifies critical path)

**Tasks:**
1. Update `@schema` decorator to run validators
2. Add provider validation config
3. Tag schemas with compatibility metadata
4. Cache validated schemas
5. Test decoration-time validation

**Deliverables:**
- [ ] Decorator runs OpenAI validators
- [ ] Schemas tagged with `_provider_compatibility`
- [ ] Schemas cached with `_validated_schema`
- [ ] 10+ tests for decorator validation
- [ ] Error messages tested and clear

**Validation:**
- Existing schemas still work
- Invalid schemas fail at import time with clear errors
- Compatibility metadata accessible

---

### Phase 3: Update Codec (1 day)
**Risk:** Low (simple changes)

**Tasks:**
1. Update codec to check compatibility
2. Use cached validated schema
3. Add `_apply_adapters()` helper
4. Remove `FlattenUnions` from adapter list
5. Run existing codec tests

**Deliverables:**
- [ ] Codec checks `_provider_compatibility`
- [ ] Codec uses `_validated_schema`
- [ ] `_apply_adapters()` helper method
- [ ] All existing tests pass
- [ ] No FlattenUnions references

**Validation:**
- Existing schemas encode correctly
- Format adapter wraps schema correctly
- No performance regression

---

### Phase 4: Schema Audit & Migration (2-3 days)
**Risk:** Medium (touches many schemas)

**Tasks:**
1. Audit ALL existing schemas for root-level unions
2. Test all schemas with new validation
3. Fix any schemas that fail validation
4. Verify all services still work
5. Run full regression test suite

**Deliverables:**
- [ ] Schema audit report (list of all schemas + status)
- [ ] 0 root-level union schemas
- [ ] All schemas pass OpenAI validation
- [ ] All services work unchanged
- [ ] Full regression tests pass

**Validation:**
- No schema validation errors in logs
- All existing functionality works
- No API errors from OpenAI

---

### Phase 5: Section Composition (Optional, 2-3 days)
**Risk:** Low (new feature, opt-in)

**Tasks:**
1. Create common section models (PatientDemographics, LabResults, etc.)
2. Update one schema to use composition pattern (pilot)
3. Update one service to extract sections
4. Add section extraction tests
5. Document pattern for Lab authors

**Deliverables:**
- [ ] 3-5 common section models
- [ ] 1 composite schema (pilot)
- [ ] 1 service using section extraction
- [ ] Section extraction tests
- [ ] Schema composition guide

**Validation:**
- Pilot schema validates correctly
- Sections extractable with correct types
- Pattern documented and clear

---

### Phase 6: Cleanup & Documentation (1 day)
**Risk:** Low (final polish)

**Tasks:**
1. Delete `FlattenUnions` class
2. Delete old `schema_adapters.py` file
3. Update developer documentation
4. Write migration guide
5. Update schema design guide for Lab authors

**Deliverables:**
- [ ] Dead code removed
- [ ] All docs updated
- [ ] Migration guide published
- [ ] Schema design guide published

**Validation:**
- No references to deleted code
- Documentation accurate
- Guides tested with team

---

## Testing Strategy

### Unit Tests

**Validators (`test_openai_validators.py`):**
- ✅ Valid object schema passes
- ✅ Nested union schema passes
- ❌ Root array schema fails
- ❌ Root union schema fails
- ❌ Missing properties fails
- ✅ Error messages are clear

**Format Adapter (`test_openai_format_adapter.py`):**
- ✅ Wraps schema correctly
- ✅ Preserves schema content
- ✅ Output is JSON-serializable

**Decorator (`test_schema_decorator.py`):**
- ✅ Valid schema decorated successfully
- ✅ Compatibility metadata added
- ✅ Schema cached
- ❌ Invalid schema fails at decoration
- ✅ Multiple providers supported (future)

**Codec (`test_responses_json_codec.py`):**
- ✅ Checks compatibility before encode
- ✅ Uses cached schema
- ✅ Applies format adapter
- ❌ Fails if schema not validated
- ✅ Decode works as before

### Integration Tests

**End-to-End:**
1. Define schema with `@schema`
2. Schema validated at import
3. Service uses schema
4. Codec encodes with format adapter
5. Mock API call
6. Codec decodes response
7. Assert typed output

**Regression:**
- All existing schemas still work
- All existing services still work
- No breaking changes

---

## Success Criteria

### Functional
- ✅ All existing schemas work (or clear migration path)
- ✅ Invalid schemas fail at import with clear errors
- ✅ Schemas tagged with provider compatibility
- ✅ Nested unions preserved (not flattened)
- ✅ No schema-related bugs in production

### Quality
- ✅ 100% coverage for validators
- ✅ 100% coverage for format adapter
- ✅ 95%+ coverage for decorator changes
- ✅ 95%+ coverage for codec changes
- ✅ All regression tests pass

### Performance
- ✅ No schema regeneration at request time (cached)
- ✅ Validation happens once (at decoration)
- ✅ No measurable latency increase

### Maintainability
- ✅ Clear separation: validate vs adapt vs encode
- ✅ Easy to add new providers
- ✅ Comprehensive documentation
- ✅ Dead code removed

---

## Migration Guide for Lab Authors

### Before
```python
@schema
class MySchema(BaseModel):
    result: Union[A, B]  # Root union - would be silently flattened
```

### After
```python
# ❌ This will fail at import:
@schema
class MySchema(BaseModel):
    result: Union[A, B]  # ERROR: Root-level unions not supported

# ✅ Fix: Wrap in container
@schema
class MySchema(BaseModel):
    result: Annotated[Union[A, B], Field(discriminator="kind")]  # Works!
```

### Error Messages
```
ValueError: MySchema: Root-level 'anyOf' unions are not supported by OpenAI.
Nested unions ARE supported. Redesign with discriminated union in a field:
  class MySchema(BaseModel):
      item: Annotated[Union[A, B], Field(discriminator='kind')]
```

---

## Rollout Strategy

### Stage 1: Deploy to Staging (Week 1)
1. Deploy changes to staging environment
2. Monitor for import errors (schema validation failures)
3. Fix any schemas that fail validation
4. Run full test suite
5. Monitor for 48 hours

**Rollback:** Revert PR if critical issues

### Stage 2: Canary (10%, Week 2)
1. Deploy to production
2. Enable for 10% of traffic
3. Monitor error rates, latency, output quality
4. Check logs for validation errors

**Rollback:** Reduce to 0% if issues

### Stage 3: Full Rollout (100%, Week 2-3)
1. Increase to 50% if stable
2. Monitor for 3 days
3. Increase to 100%
4. Monitor for 1 week

**Rollback:** Reduce percentage if issues

### Stage 4: Cleanup (Week 3)
1. Remove dead code (FlattenUnions)
2. Update documentation
3. Mark migration complete

---

## Monitoring & Alerts

### Metrics to Track

**Pre-Deploy (Baseline):**
- Schema validation time: N/A (new metric)
- Codec encode time: 5-10ms average
- API error rate: <0.1% (400 errors)
- Parsing error rate: <0.5%

**Post-Deploy (Expected):**
- Schema validation time: One-time at import (negligible)
- Codec encode time: 3-8ms (faster - uses cache)
- API error rate: Same or lower (better validation)
- Parsing error rate: Same or lower

**Alerts:**
- Import failures (schema validation errors)
- API 400 errors increase >5%
- Codec encode time increase >50%
- Parsing errors increase >10%

---

## Open Decisions

### 1. Should validation be opt-out or always-on?
**Current:** Always-on (fail-fast)
**Alternative:** Allow `_skip_validation = True` flag
**Decision needed:** Before Phase 2
**Recommendation:** Always-on (simpler, safer)

### 2. Should we support multiple providers immediately?
**Current:** OpenAI only
**Alternative:** Add Anthropic validation config (disabled)
**Decision needed:** Before Phase 2
**Recommendation:** OpenAI only, add structure for future

### 3. Should we cache schemas at class level or instance level?
**Current:** Class level (`cls._validated_schema`)
**Alternative:** Instance-level cache
**Decision needed:** Before Phase 2
**Recommendation:** Class level (schemas are immutable)

### 4. Should we add schema size warnings?
**Current:** No size validation
**Alternative:** Warn if schema >10KB
**Decision needed:** Before Phase 1
**Recommendation:** Add later if needed

---

## Timeline

```
Week 1:
  Mon-Tue: Phase 1 (validators + adapter)
  Wed-Thu: Phase 2 (decorator)
  Fri:     Phase 3 (codec)

Week 2:
  Mon-Tue: Phase 4 (schema audit + fixes)
  Wed:     Deploy to staging
  Thu-Fri: Monitor staging, fix issues

Week 3:
  Mon:     Deploy canary (10%)
  Wed:     Increase to 50%
  Fri:     Increase to 100%

Week 4:
  Mon-Tue: Phase 5 (section composition, optional)
  Wed:     Phase 6 (cleanup)
  Thu:     Final review
  Fri:     Post-implementation review
```

**Total Duration:** 3-4 weeks (including monitoring)

---

## Risk Assessment

### Low Risk ✅
- Adding validators (new code, parallel)
- Updating codec (simple changes, well-tested)
- Section composition (opt-in feature)

### Medium Risk ⚠️
- Updating decorator (critical path, affects all schemas)
  - **Mitigation:** Comprehensive tests, gradual rollout
- Schema migration (unknown number of failures)
  - **Mitigation:** Audit first, fix in staging

### High Risk ❌
None identified. All major risks mitigated.

---

## Checklist for Implementation Start

### Before Phase 1
- [ ] This plan reviewed and approved
- [ ] Open decisions resolved
- [ ] Test strategy agreed upon
- [ ] Create feature branch from `orchestrai_v0.4.0`

### Before Each Phase
- [ ] Review phase plan
- [ ] Write tests first (TDD)
- [ ] Monitor test coverage

### Before Merge
- [ ] All tests pass
- [ ] Coverage thresholds met (95%+)
- [ ] Code reviewed by 2+ engineers
- [ ] Documentation updated

### Before Deploy
- [ ] Staging tests pass
- [ ] Schema audit complete
- [ ] Rollback plan tested
- [ ] Team notified

---

## Summary

**What's Different from v1:**
- ❌ No SchemaBuilder class (validation in decorator)
- ❌ No FormatBuilder class (stays as adapter)
- ✅ Validators in provider-specific location
- ✅ Validation at decoration time (fail-fast)
- ✅ Schema compatibility tagging
- ✅ Simpler architecture, fewer new concepts

**Estimated Effort:** 8-12 developer-days (vs 15-20 in v1)

**Key Benefits:**
1. Simpler (no new builder classes)
2. Faster (fail at import, not runtime)
3. Cleaner (validation where schemas are defined)
4. Extensible (easy to add providers)

**Status:** READY FOR REVIEW

**Next Steps:**
1. Review this plan
2. Resolve open decisions
3. Get approval
4. Begin Phase 1
