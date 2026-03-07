# Schema Modernization Plan - Comprehensive Review

**Review Date:** 2026-01-02
**Status:** Ready for Approval
**Estimated Effort:** 8-12 developer-days (2-3 weeks)

---

## Executive Summary

This review walks through the complete schema modernization plan from start to finish, highlighting key decisions, risks, and next steps.

---

## 1. What Problem Are We Solving?

### Current Issues

**Problem 1: Over-Aggressive Adaptation**
- `FlattenUnions` adapter flattens ALL unions (root + nested)
- OpenAI NOW supports nested unions (as of 2024+)
- Flattening loses type safety (discriminated unions become bags of properties)

**Problem 2: Late Error Detection**
- Schema validation happens at response processor encode time (request time)
- Invalid schemas don't fail until user hits endpoint
- Errors hard to trace back to schema definition

**Problem 3: No Provider Compatibility Tracking**
- Can't tell if schema was validated for OpenAI
- Can't easily support multiple providers
- No metadata about schema compatibility

**Problem 4: Performance**
- Schema regenerated on every request
- No caching of validated schemas

### Proposed Solutions

✅ **Remove FlattenUnions** - Nested unions work now
✅ **Validate at decoration time** - Fail at import, not runtime
✅ **Tag schemas with compatibility** - Track what's validated
✅ **Cache validated schemas** - Generate once, reuse

---

## 2. Core Architecture Decision

### The Key Insight
**Don't need SchemaBuilder class - validate in the decorator.**

### Why This Works
1. **All schemas use `@schema` decorator** (100% coverage)
2. **Validation happens at import** (fail-fast)
3. **No new classes needed** (simpler)
4. **Clear error context** (stack trace points to schema definition)

### Architecture Flow

```
┌────────────────────────────────────────────┐
│ Lab Author Defines Schema                  │
│                                            │
│   @schema                                  │
│   class PatientSchema(BaseModel):         │
│       patient: PatientDemographics        │
└────────────────────────────────────────────┘
                    ↓
┌────────────────────────────────────────────┐
│ Decoration Time (Module Import)            │
│                                            │
│   1. Generate JSON Schema (Pydantic)       │
│   2. Run validators (OpenAI rules)         │
│   3. Tag with metadata                     │
│   4. Cache schema                          │
│   5. Register component                    │
│                                            │
│   FAILS HERE if schema invalid             │
└────────────────────────────────────────────┘
                    ↓
┌────────────────────────────────────────────┐
│ Request Time (Service Call)                │
│                                            │
│   1. Response processor checks compatibility tag        │
│   2. Uses cached schema                    │
│   3. Applies format adapter                │
│   4. Attaches to request                   │
│                                            │
│   Fast - no regeneration, no validation    │
└────────────────────────────────────────────┘
```

---

## 3. File Organization

### New Structure

```
packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/
├── schema/                          # NEW DIRECTORY
│   ├── __init__.py
│   ├── validate.py                 # Validation rules
│   └── adapt.py                    # Format adapter
├── openai.py                       # Provider (no changes)
├── request_builder.py              # Request builder (no changes)
└── constants.py                    # Constants (no changes)
```

**Why this structure?**
- ✅ Provider-specific logic lives together
- ✅ Clear separation: validate vs adapt
- ✅ Easy to find: `openai/schema/` is obvious location
- ✅ Extensible: Add new providers with same pattern

### Deleted Files

```
packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/
└── schema_adapters.py              # DELETED (split into validate.py + adapt.py)
```

---

## 4. Validation Rules

### OpenAI Constraints (Validated)

| Rule | Check | Error If... |
|------|-------|-------------|
| `root_is_object` | Root `type` is `"object"` | Root is array, string, etc. |
| `no_root_unions` | No `anyOf`/`oneOf` at root | Root-level union detected |
| `has_properties` | Root has `properties` field | Empty model |

### What's NOT Validated

These are **intentionally not checked** (OpenAI supports them):

❌ Nested unions (supported!)
❌ Discriminated unions (supported!)
❌ Optional fields (supported!)
❌ Arrays (supported!)
❌ Complex nesting (supported!)

### Example Error Messages

**Good error message:**
```
ValueError: PatientSchema: Root-level 'anyOf' unions are not supported by OpenAI.
Nested unions ARE supported. Redesign with discriminated union in a field:
  class PatientSchema(BaseModel):
      item: Annotated[Union[A, B], Field(discriminator='kind')]

File: chatlab/orca/schemas/patient.py, line 15
```

**What makes it good:**
- ✅ Names the schema
- ✅ Explains the problem
- ✅ Explains nested unions ARE OK
- ✅ Shows how to fix it
- ✅ Points to exact file/line

---

## 5. Provider Compatibility Tagging

### Schema Metadata

After decoration, schemas have:

```python
@schema
class PatientSchema(BaseModel):
    patient: PatientDemographics

# After decoration:
PatientSchema._provider_compatibility = {
    "openai": True,  # Passed validation
}
PatientSchema._validated_schema = {...}  # Cached JSON Schema
PatientSchema._validated_at = "decoration"
```

### How Response processor Uses Metadata

```python
# In response processor.aencode():
schema_cls = req.response_schema

# Check compatibility
if not schema_cls._provider_compatibility.get("openai"):
    raise CodecSchemaError(
        f"Schema {schema_cls.__name__} not validated for OpenAI"
    )

# Use cached schema (no regeneration)
schema = schema_cls._validated_schema

# Apply format adapter
adapted = self._apply_adapters(schema)
```

### Future: Multiple Providers

```python
PROVIDER_VALIDATION_CONFIG = {
    "openai": {
        "enabled": True,
        "strict": True,
        "validator": validate_openai_schema,
    },
    "anthropic": {
        "enabled": False,  # Not yet
        "strict": False,
        "validator": validate_anthropic_schema,
    },
}

# After decoration:
MySchema._provider_compatibility = {
    "openai": True,
    "anthropic": False,  # Didn't validate (disabled)
}
```

---

## 6. Format Adapter (Keep as Adapter)

### Why Keep as Adapter?

**Format wrapping IS adaptation** - transforming from:
- Generic JSON Schema: `{"type": "object", ...}`
- Provider envelope: `{"format": {"type": "json_schema", "schema": {...}}}`

### OpenaiFormatAdapter

```python
class OpenaiFormatAdapter(BaseSchemaAdapter):
    order = 999  # Run last

    def adapt(self, schema: dict) -> dict:
        """Wrap in OpenAI envelope."""
        return {
            "format": {
                "type": "json_schema",
                "name": "response",
                "schema": schema,
            }
        }
```

**This is the ONLY adapter now** (FlattenUnions deleted).

---

## 7. What Gets Deleted?

### FlattenUnions Adapter

**Why delete?**
1. OpenAI supports nested unions now
2. Flattening loses type safety
3. Existing `MetafieldItem` proves discriminated unions work

**Proof it's safe to delete:**
- Documentation confirms nested unions supported
- Existing schemas use discriminated unions successfully
- No schemas should have root-level unions (decorator will catch them)

### Old schema_adapters.py File

**Replaced by:**
- `schema/validate.py` - Validation rules
- `schema/adapt.py` - Format adapter

**Cleaner separation of concerns.**

---

## 8. Migration Impact

### Schemas That Work Without Changes

✅ **All schemas with object root**
✅ **All schemas with nested unions**
✅ **All schemas with discriminated unions**
✅ **All existing SimWorks schemas** (likely 100%)

### Schemas That Need Fixing

❌ **Schemas with root-level unions** (extremely rare, likely 0)

### Example Fix

**Before (would silently flatten):**
```python
@schema
class ResultSchema(BaseModel):
    __root__: Union[Success, Error]  # Root union
```

**After (explicit error + fix):**
```python
# Error at import:
# ValueError: ResultSchema: Root-level unions not supported

# Fix:
@schema
class ResultSchema(BaseModel):
    result: Annotated[Union[Success, Error], Field(discriminator="kind")]
```

---

## 9. Implementation Phases Walkthrough

### Phase 1: Add Validation Infrastructure (2-3 days)

**What:** Create validators + format adapter
**Risk:** Low (new code, parallel)
**Deliverable:** Testable validators, no changes to existing code

**Files created:**
- `openai/schema/validate.py` (validators)
- `openai/schema/adapt.py` (format adapter)
- `tests/openai/schema/test_validators.py` (tests)

**Success criteria:**
- Validators reject invalid schemas with clear errors
- Validators pass valid schemas
- Format adapter wraps correctly
- 100% test coverage

---

### Phase 2: Update Schema Decorator (2 days)

**What:** Add validation to `@schema` decorator
**Risk:** Medium (critical path)
**Deliverable:** Schemas validated at decoration time

**Files modified:**
- `orchestrai_django/decorators/schema.py` (add validation)

**Success criteria:**
- Invalid schemas fail at import
- Valid schemas get tagged with compatibility
- Schemas get cached
- Clear error messages

**Test strategy:**
- Define test schema with root union → assert ValueError
- Define test schema with nested union → assert passes
- Check `_provider_compatibility` metadata added

---

### Phase 3: Update Response processor (1 day)

**What:** Check compatibility, use cached schema
**Risk:** Low (simple changes)
**Deliverable:** Response processor uses new validation workflow

**Files modified:**
- `orchestrai/contrib/provider_formats/openai/responses_json.py`

**Changes:**
1. Check `_provider_compatibility` before encode
2. Use `_validated_schema` (cached)
3. Add `_apply_adapters()` helper
4. Remove `FlattenUnions` from adapter list

**Success criteria:**
- Existing tests pass
- Schema not regenerated
- Format adapter applied correctly

---

### Phase 4: Schema Audit & Migration (2-3 days)

**What:** Find and fix any invalid schemas
**Risk:** Medium (scope unknown until audit)
**Deliverable:** All schemas pass validation

**Process:**
1. Run app in staging
2. Watch for import errors
3. List all schemas that fail
4. Fix each one (wrap root unions)
5. Re-test

**Expected result:** 0 schemas need fixing (all likely valid already)

---

### Phase 5: Section Composition (Optional, 2-3 days)

**What:** Add composable section pattern
**Risk:** Low (new feature, opt-in)
**Deliverable:** Pilot schema with sections

**Example:**
```python
@schema
class PatientOutputSchema(BaseModel):
    patient: PatientDemographics  # Section 1
    labs: LabResults              # Section 2
    messages: list[OutputItem]    # Section 3
```

**Benefits:**
- Type-safe section extraction
- Per-section persistence handlers
- Reusable section models

---

### Phase 6: Cleanup & Documentation (1 day)

**What:** Delete dead code, update docs
**Risk:** Low (final polish)
**Deliverable:** Clean codebase, updated docs

**Tasks:**
- Delete `FlattenUnions` class
- Delete `schema_adapters.py`
- Update developer docs
- Write migration guide for Labs

---

## 10. Testing Strategy

### Test Coverage Targets

| Module | Target | Critical Paths |
|--------|--------|----------------|
| `schema/validate.py` | 100% | All validation rules |
| `schema/adapt.py` | 100% | Format wrapping |
| `decorators/schema.py` | 95% | Validation + tagging |
| `response processors/openai/responses_json.py` | 95% | Check compatibility, cache |

### Test Matrix

**Validators:**
- ✅ Valid object schema → passes
- ✅ Nested union schema → passes
- ❌ Root array → fails with clear error
- ❌ Root union → fails with clear error
- ❌ No properties → fails with clear error

**Decorator:**
- ✅ Valid schema decorated → metadata added
- ❌ Invalid schema decorated → ValueError at import
- ✅ Multiple providers (future) → compatibility dict

**Response processor:**
- ✅ Compatible schema → encodes
- ❌ Incompatible schema → CodecSchemaError
- ✅ Cached schema used → no regeneration

**Integration:**
- ✅ Define schema → validate → encode → decode → typed output

---

## 11. Rollout Plan

### Week 1: Staging Deploy

**Steps:**
1. Merge PR to `orchestrai_v0.4.0`
2. Deploy to staging
3. Monitor for import errors
4. Fix any schemas that fail
5. Run full test suite

**Success criteria:**
- 0 import errors
- All tests pass
- No performance regression

---

### Week 2: Canary Deploy

**Steps:**
1. Deploy to production
2. Enable for 10% of traffic
3. Monitor for 2 days
4. Increase to 50%
5. Monitor for 2 days
6. Increase to 100%

**Metrics to watch:**
- Import errors: expect 0
- API 400 errors: expect same or lower
- Response processor encode time: expect same or faster
- Parsing errors: expect same

**Rollback trigger:**
- Any import errors
- API errors increase >5%
- Performance degradation >10%

---

### Week 3: Cleanup

**Steps:**
1. Delete `FlattenUnions` class
2. Delete `schema_adapters.py`
3. Update docs
4. Post-implementation review

---

## 12. Decisions Required

### Decision 1: Validation Opt-Out?

**Question:** Should schemas be able to skip validation?

**Option A:** Always validate (recommended)
```python
# All schemas validated, no opt-out
@schema
class MySchema(BaseModel):
    ...
```

**Option B:** Allow opt-out
```python
@schema
class ExperimentalSchema(BaseModel):
    _skip_validation = True  # Skip OpenAI validation
    ...
```

**Recommendation:** **Option A** (always validate)

**Why:**
- Simpler (no special cases)
- Safer (no accidental skips)
- Clearer (all schemas follow same rules)

**When to decide:** Before Phase 2
**Who decides:** Tech lead + team

---

### Decision 2: Multiple Provider Support?

**Question:** Should we add Anthropic validation config now?

**Option A:** OpenAI only (recommended)
```python
PROVIDER_VALIDATION_CONFIG = {
    "openai": {
        "enabled": True,
        "validator": validate_openai_schema,
    },
}
```

**Option B:** Add Anthropic (disabled)
```python
PROVIDER_VALIDATION_CONFIG = {
    "openai": {
        "enabled": True,
        "validator": validate_openai_schema,
    },
    "anthropic": {
        "enabled": False,  # For future
        "validator": None,  # Not implemented yet
    },
}
```

**Recommendation:** **Option A** (OpenAI only)

**Why:**
- YAGNI (you aren't gonna need it yet)
- Easy to add later when needed
- No complexity for hypothetical feature

**When to decide:** Before Phase 2
**Who decides:** Tech lead

---

### Decision 3: Schema Size Limits?

**Question:** Should we warn about large schemas?

**Option A:** No size validation (recommended for now)
```python
# Just validate structure, not size
```

**Option B:** Add size warning
```python
if len(json.dumps(schema)) > 10_000:  # 10KB
    logger.warning(f"{name}: Schema is {size}KB, may hit token limits")
```

**Recommendation:** **Option A** (no size validation)

**Why:**
- No known issues with large schemas
- Easy to add later if needed
- Keeps validators focused

**When to decide:** Before Phase 1
**Who decides:** Tech lead

**Alternative:** Add later if we see issues in production

---

### Decision 4: Cache Location?

**Question:** Where to cache validated schemas?

**Option A:** Class attribute (recommended)
```python
cls._validated_schema = schema  # On the class
```

**Option B:** Module-level cache
```python
_SCHEMA_CACHE = {}  # Module global
_SCHEMA_CACHE[cls] = schema
```

**Recommendation:** **Option A** (class attribute)

**Why:**
- Simple (no global state)
- Clear ownership (cache lives with schema)
- Thread-safe (classes are immutable)

**When to decide:** Before Phase 2
**Who decides:** Tech lead

---

## 13. Risk Assessment Summary

### Low Risk ✅

**Adding validators:**
- New code, doesn't affect existing
- Comprehensive tests
- Easy to rollback

**Updating response processor:**
- Simple changes
- Existing tests cover behavior
- Performance improvement (caching)

**Section composition:**
- Opt-in feature
- Doesn't affect existing schemas

### Medium Risk ⚠️

**Updating decorator:**
- Critical path (all schemas go through it)
- Changes behavior (validation at import)
- **Mitigation:** Thorough testing, staged rollout

**Schema migration:**
- Unknown scope (how many schemas fail?)
- **Mitigation:** Audit in staging first, fix before production

### High Risk ❌

**None identified.**

All risks have clear mitigation strategies.

---

## 14. Performance Impact

### Before (Current)

```
Request arrives
  → Service builds request
  → Response processor.encode()
    → Generate schema (5-10ms)     ← EVERY REQUEST
    → Flatten unions (2-5ms)        ← EVERY REQUEST
    → Wrap in format (0.5ms)
  → Send to OpenAI
```

**Total overhead per request:** ~8-16ms

### After (New)

```
App startup
  → @schema decorator runs
    → Generate schema (5-10ms)      ← ONCE
    → Validate (1ms)                ← ONCE
    → Cache (0.1ms)

Request arrives
  → Service builds request
  → Response processor.encode()
    → Check compatibility (0.1ms)
    → Use cached schema (0.1ms)     ← FAST
    → Wrap in format (0.5ms)
  → Send to OpenAI
```

**Total overhead per request:** ~0.7ms

**Improvement:** ~10-15ms faster per request

---

## 15. Success Metrics

### Deployment Metrics

**Must achieve:**
- ✅ 0 import errors in staging
- ✅ 0 import errors in production
- ✅ All existing tests pass
- ✅ No API 400 error increase

**Nice to have:**
- ✅ Response processor encode time reduced by >5ms
- ✅ Schema validation errors have helpful messages
- ✅ Team understands new pattern

### Quality Metrics

**Must achieve:**
- ✅ 100% test coverage for validators
- ✅ 95%+ test coverage for decorator changes
- ✅ 95%+ test coverage for response processor changes
- ✅ All regression tests pass

**Nice to have:**
- ✅ Documentation complete and reviewed
- ✅ Migration guide tested with Labs
- ✅ Post-implementation review completed

---

## 16. Timeline Summary

```
Week 1: Implementation
├─ Mon-Tue: Phase 1 (validators + adapter)
├─ Wed-Thu: Phase 2 (decorator)
└─ Fri:     Phase 3 (response processor)

Week 2: Testing & Staging
├─ Mon-Tue: Phase 4 (schema audit)
├─ Wed:     Deploy to staging
└─ Thu-Fri: Monitor staging

Week 3: Production Rollout
├─ Mon:     Deploy canary (10%)
├─ Wed:     Increase to 50%
└─ Fri:     Increase to 100%

Week 4: Optional Features & Cleanup
├─ Mon-Tue: Phase 5 (section composition)
├─ Wed:     Phase 6 (cleanup)
└─ Thu-Fri: Final review
```

**Total: 3-4 weeks**

---

## 17. Pre-Implementation Checklist

### Documentation Review
- [ ] This plan reviewed by tech lead
- [ ] This plan reviewed by team
- [ ] Open decisions resolved
- [ ] Test strategy approved

### Technical Preparation
- [ ] Feature branch created from `orchestrai_v0.4.0`
- [ ] Test fixtures prepared
- [ ] CI pipeline ready
- [ ] Staging environment accessible

### Team Alignment
- [ ] Team briefed on changes
- [ ] Labs notified of validation changes
- [ ] Rollout plan approved
- [ ] Rollback procedure documented

---

## 18. Open Questions

### Technical Questions

**Q: What if a schema is used by multiple services with different providers?**
A: Schema is validated for all enabled providers. If service needs provider X, check `_provider_compatibility["x"]`.

**Q: Can we add custom validation rules per Lab?**
A: Yes, add to `PROVIDER_VALIDATION_CONFIG` with Lab-specific validator function.

**Q: What if OpenAI changes their rules again?**
A: Update validators in `openai/schema/validate.py`, redeploy. Schemas automatically re-validated.

### Process Questions

**Q: Who approves schema migrations?**
A: Tech lead approves plan, Labs fix their own schemas.

**Q: What if a Lab needs to deploy during migration?**
A: Migration is backward compatible. New code works with all existing schemas.

**Q: How do we communicate breaking changes?**
A: Import errors are breaking changes. Fix in staging before production deploy.

---

## 19. Next Steps

### Immediate (This Week)
1. **Review this plan** with tech lead
2. **Resolve open decisions** (4 decisions listed above)
3. **Get team approval** for implementation
4. **Create feature branch** from `orchestrai_v0.4.0`

### Week 1 (Implementation)
1. **Phase 1:** Implement validators + adapter
2. **Phase 2:** Update decorator
3. **Phase 3:** Update response processor
4. **Daily:** Review progress, adjust timeline

### Week 2 (Testing)
1. **Phase 4:** Schema audit in staging
2. **Deploy to staging**
3. **Monitor for issues**
4. **Fix any schemas that fail**

### Week 3 (Rollout)
1. **Deploy canary** (10%)
2. **Monitor metrics**
3. **Increase to 100%**
4. **Celebrate success** 🎉

---

## 20. Approval Sign-Off

### Required Approvals

| Role | Name | Status | Date |
|------|------|--------|------|
| Tech Lead | TBD | ⏳ Pending | - |
| Backend Team Lead | TBD | ⏳ Pending | - |
| QA Lead | TBD | ⏳ Pending | - |
| DevOps | TBD | ⏳ Pending | - |

### Open Decisions to Resolve

| Decision | Options | Recommendation | Approver | Status |
|----------|---------|----------------|----------|--------|
| Validation opt-out? | Always / Optional | Always | Tech Lead | ⏳ Pending |
| Multiple providers? | OpenAI only / Add Anthropic | OpenAI only | Tech Lead | ⏳ Pending |
| Schema size limits? | No / Warn >10KB | No | Tech Lead | ⏳ Pending |
| Cache location? | Class / Module | Class | Tech Lead | ⏳ Pending |

---

## 21. Final Recommendation

**PROCEED with implementation** based on this plan.

**Confidence Level:** High (90%+)

**Reasons:**
1. ✅ Architecture is simpler than v1 (no SchemaBuilder class)
2. ✅ Validation happens early (decoration time)
3. ✅ Low risk (new code parallel, gradual rollout)
4. ✅ Clear benefits (performance, type safety, maintainability)
5. ✅ Well-tested strategy (comprehensive test plan)
6. ✅ Easy rollback (feature flag or revert PR)

**Concerns:**
1. ⚠️ Unknown number of schemas may fail validation
   - **Mitigation:** Audit in staging first
2. ⚠️ Decorator changes affect critical path
   - **Mitigation:** Comprehensive tests, staged rollout

**Overall:** Benefits outweigh risks. Ready to proceed.

---

## 22. Questions for Review

### For Tech Lead
1. Approve overall architecture approach?
2. Approve test coverage targets (95%+)?
3. Approve rollout strategy (canary → 100%)?
4. Resolve 4 open decisions?

### For Backend Team
1. Any concerns with decorator-based validation?
2. Any concerns with caching strategy?
3. Any edge cases we missed?

### For QA
1. Test strategy sufficient?
2. Staging test plan clear?
3. Rollback procedure clear?

### For DevOps
1. Deployment plan feasible?
2. Monitoring alerts sufficient?
3. Rollback procedure tested?

---

**END OF REVIEW**

**Status:** ✅ Complete - Ready for Team Review
**Next Action:** Schedule review meeting with approvers
**Target Start Date:** TBD (after approvals)
