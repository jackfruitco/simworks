# Schema Modernization Implementation Plan

**Status:** PLAN & REVIEW - No code changes yet
**Branch:** `orchestrai_v0.4.0`
**Target Completion:** 15-20 developer-days (3-4 weeks)

---

## Executive Summary

This plan modernizes the **entire structured-output schema workflow** in SimWorks/OrchestrAI to:

1. ✅ **Align with current OpenAI Responses API** (2026 specification)
2. ✅ **Remove unnecessary schema transformations** (FlattenUnions is obsolete)
3. ✅ **Preserve type safety** (discriminated unions work correctly)
4. ✅ **Enable composable schemas** (per-Lab section types)
5. ✅ **Improve testability** (100% branch coverage for core pipeline)
6. ✅ **Simplify maintenance** (clear separation of concerns, minimal adapters)

**Key Finding:** OpenAI **supports** `anyOf`/`oneOf` in **nested properties**, but **rejects** them at **root level**. Current `FlattenUnions` adapter over-adapts by flattening ALL unions, losing type safety unnecessarily.

**Recommendation:** Remove `FlattenUnions` and enforce good schema design via validation.

---

## Planning Documents

### 1. OpenAI Schema Notes
**File:** `docs/openai_schema_notes.md`

**Contents:**
- Current OpenAI API constraints (Responses API vs Chat Completions)
- Supported/unsupported JSON Schema features
- Exact request shape for `responses.create`
- Union support clarification (nested OK, root NOT OK)
- Strict mode requirements
- Common failure patterns with fixes

**Key Takeaway:** Nested unions work—don't flatten them.

---

### 2. Schema Workflow Map
**File:** `docs/schema_workflow_map.md`

**Contents:**
- Complete end-to-end workflow (definition → persistence)
- File paths for all schema-related code
- Current implementation analysis
- Identified issues (over-flattening, no section composition, etc.)
- Quick reference table of key files and functions

**Key Takeaway:** Current workflow has 5 identified issues, all solvable.

---

### 3. Schema Pipeline Architecture
**File:** `docs/schema_pipeline_architecture.md`

**Contents:**
- Canonical pipeline design (SchemaBuilder → FormatBuilder → Codec → Provider)
- Component interfaces and responsibilities
- Section composition pattern for per-Lab schemas
- Migration path (5 phases)
- Error handling strategy
- Success criteria and open questions

**Key Takeaway:** Single source of truth for schema generation with clear boundaries.

---

### 4. FlattenUnions Evaluation
**File:** `docs/flatten_unions_evaluation.md`

**Contents:**
- Current implementation analysis
- Evidence that OpenAI supports nested unions
- Existing SimWorks proof (MetafieldItem works)
- Proof-of-concept test plan
- Recommendation: REMOVE adapter
- Risk assessment (low risk)

**Key Takeaway:** FlattenUnions is obsolete; removing it improves type safety.

---

### 5. Test Coverage Plan
**File:** `docs/test_coverage_plan.md`

**Contents:**
- Comprehensive test matrix (14 test suites)
- 100% branch coverage targets for core modules
- Golden output tests
- Live API tests (optional, gated)
- Regression test checklist
- Test execution strategy

**Key Takeaway:** Full test coverage ensures no regressions, all branches validated.

---

## Implementation Phases

### Phase 1: New Pipeline (Parallel to Existing)
**Duration:** 3-4 days
**Risk:** Low (no changes to existing code)

**Tasks:**
1. Create `orchestrai/schemas/builder.py` with `SchemaBuilder` class
2. Create `orchestrai/schemas/format_builder.py` with `FormatBuilder` class
3. Write comprehensive unit tests (100% branch coverage)
4. Add validation rules (root must be object, no root unions, etc.)
5. Document APIs

**Deliverables:**
- [ ] `SchemaBuilder.build()` method with validation
- [ ] `FormatBuilder.build_openai_responses_format()` method
- [ ] `SchemaValidationError` exception class
- [ ] 30+ unit tests (all passing)
- [ ] 100% coverage for new modules

**Validation:**
- All tests green
- No changes to existing codec yet
- Golden output snapshots created

---

### Phase 2: Update OpenAI Codec
**Duration:** 3 days
**Risk:** Medium (modifies critical path)

**Tasks:**
1. Update `OpenAIResponsesJsonCodec.aencode()` to use new pipeline
2. Remove `FlattenUnions` and `OpenaiWrapper` from adapter list
3. Add new tests for edge cases (root union rejected, nested union preserved)
4. Run existing codec test suite (should pass)
5. Add golden output tests for codec

**Deliverables:**
- [ ] Codec uses SchemaBuilder + FormatBuilder
- [ ] No more schema adapters (or minimal pass-through)
- [ ] All existing tests pass
- [ ] 10+ new tests for validation errors
- [ ] 95%+ codec coverage

**Validation:**
- Existing schemas work unchanged
- Root union schemas fail with clear error
- Nested unions preserved in output

---

### Phase 3: Section Composition Framework (Opt-In)
**Duration:** 2-3 days
**Risk:** Low (new feature, opt-in)

**Tasks:**
1. Create common section models (`PatientDemographics`, `LabResults`, etc.)
2. Create `SectionRegistry` for section type + handler registration
3. Update ONE schema to use composition pattern (pilot: `PatientInitialOutputSchema`)
4. Update ONE service to extract and route sections
5. Add persistence handler stubs for pilot sections
6. Test end-to-end with mock API

**Deliverables:**
- [ ] `SectionRegistry` class
- [ ] 3-5 common section models
- [ ] 1 composite schema (pilot)
- [ ] 1 service updated to use sections
- [ ] Section extraction + routing tests
- [ ] Documentation for Lab authors

**Validation:**
- Pilot schema works end-to-end
- Sections extractable with correct types
- Persistence handlers callable

---

### Phase 4: Schema Migration
**Duration:** 3-5 days
**Risk:** Medium (touches many schemas)

**Tasks:**
1. Audit ALL existing schemas for root-level unions
2. Redesign any root-level unions as container objects (likely none)
3. Migrate remaining schemas to composition pattern (where beneficial)
4. Update services to extract sections (where applicable)
5. Expand persistence handlers for new sections
6. Run full regression test suite

**Deliverables:**
- [ ] Schema audit report (list of all schemas + compliance status)
- [ ] 0 root-level union schemas
- [ ] 5-10 schemas migrated to composition pattern
- [ ] 5-10 services updated to use sections
- [ ] Persistence handlers for all section types
- [ ] All regression tests pass

**Validation:**
- All schemas pass validation
- All services work unchanged or improved
- No performance degradation

---

### Phase 5: Cleanup and Documentation
**Duration:** 2 days
**Risk:** Low (final polish)

**Tasks:**
1. Delete `FlattenUnions` class (dead code)
2. Delete `OpenaiWrapper` class (logic moved to FormatBuilder)
3. Update developer documentation
4. Write migration guide for external contributors
5. Write schema design guide for Lab authors
6. Final review of all documentation
7. Create summary presentation

**Deliverables:**
- [ ] Dead code removed
- [ ] All docs updated
- [ ] Migration guide published
- [ ] Schema design guide published
- [ ] Presentation slides (if needed)

**Validation:**
- No references to deleted classes
- Documentation accurate and complete
- Stakeholders briefed

---

## Success Criteria

### Functional Requirements
- ✅ All existing schemas work without modification OR clear migration path
- ✅ New schemas can use nested unions without issues
- ✅ Root-level union designs caught at encode time with helpful error
- ✅ Section composition works end-to-end for at least 1 Lab
- ✅ No schema-related bugs in production after deploy

### Quality Requirements
- ✅ 100% branch coverage for SchemaBuilder
- ✅ 100% branch coverage for FormatBuilder
- ✅ 95%+ coverage for codec encode/decode
- ✅ 90%+ coverage for provider integration
- ✅ All regression tests pass
- ✅ Live API test passes (at least 1 complex schema)

### Performance Requirements
- ✅ Schema generation time < 10ms for typical schemas
- ✅ No measurable latency increase in request build
- ✅ Codec encode/decode performance unchanged or improved

### Maintainability Requirements
- ✅ Clear module boundaries (no circular dependencies)
- ✅ Comprehensive inline documentation
- ✅ Migration guide written and tested
- ✅ Dead code removed

---

## Risk Assessment

### High-Risk Items
1. **Codec migration could break existing schemas**
   - **Mitigation:** Comprehensive regression tests, gradual rollout
   - **Rollback:** Keep old codec in git history, feature flag if needed

2. **OpenAI API could reject schemas we think are valid**
   - **Mitigation:** Proof-of-concept tests with live API before full migration
   - **Rollback:** Re-introduce minimal adapter if specific edge case found

### Medium-Risk Items
1. **Schema migration could be time-consuming**
   - **Mitigation:** Start with audit, identify scope early
   - **Fallback:** Migrate in batches, prioritize critical schemas

2. **Section composition could be complex to implement**
   - **Mitigation:** Opt-in approach, pilot with 1 schema first
   - **Fallback:** Skip composition if pilot fails, keep monolithic schemas

### Low-Risk Items
1. **Test coverage could be hard to achieve**
   - **Mitigation:** TDD approach, write tests first
   - **Fallback:** 90% coverage acceptable if 100% not feasible

2. **Documentation could drift out of sync**
   - **Mitigation:** Update docs in same PR as code changes
   - **Fallback:** Dedicated doc review pass at end

---

## Dependencies and Blockers

### External Dependencies
- **OpenAI API availability** for live tests
- **OpenAI Python SDK** version compatibility (should be latest)

### Internal Dependencies
- Access to staging environment for integration testing
- Database access for persistence tests
- Coordination with Labs for schema migration

### Potential Blockers
- **Unknown OpenAI constraints** not documented
  - **Resolution:** Run live API tests early to discover issues
- **Breaking changes in existing schemas** we're not aware of
  - **Resolution:** Comprehensive audit before migration
- **Performance issues with new pipeline**
  - **Resolution:** Benchmark before/after, optimize if needed

---

## Rollout Strategy

### Stage 1: Canary (1 service, 1 schema)
**Target:** `GenerateInitialResponse` with `PatientInitialOutputSchema`

**Steps:**
1. Deploy new pipeline to staging
2. Enable for ONE service only (feature flag)
3. Monitor for 48 hours
4. Check error rates, latency, output quality
5. If stable, proceed to Stage 2

**Rollback:** Disable feature flag, revert to old codec

### Stage 2: Gradual Rollout (10% → 50% → 100%)
**Targets:** All chatlab services → All simulation services → All services

**Steps:**
1. Enable for 10% of traffic (random sampling)
2. Monitor for 1 week
3. Increase to 50% if stable
4. Monitor for 1 week
5. Increase to 100% if stable

**Rollback:** Reduce percentage or disable entirely

### Stage 3: Cleanup
**After 2 weeks at 100%:**
1. Remove feature flag code
2. Delete old adapter classes
3. Mark migration complete

---

## Monitoring and Validation

### Metrics to Track

**Pre-Deploy (Baseline):**
- Schema generation time (avg, p95, p99)
- Request build time
- Codec encode/decode time
- API error rate (400 schema errors)
- Parsing error rate (validation failures)

**Post-Deploy (Compare):**
- Same metrics, expect:
  - ✅ Schema generation time: same or better
  - ✅ Request build time: same
  - ✅ API error rate: same or lower (better validation)
  - ✅ Parsing error rate: same or lower (stricter schemas)

**Alerts:**
- Increase in 400 errors > 5% over baseline
- Increase in parsing errors > 5% over baseline
- Latency p95 increase > 10ms

---

## Communication Plan

### Stakeholders
1. **Engineering Team** - Schema modernization plan, migration timeline
2. **Lab Authors** - Schema design guide, migration support
3. **QA Team** - Test plan, validation checklist
4. **DevOps** - Deployment plan, rollback procedure

### Updates
- **Weekly:** Progress update in team standup
- **Phase completion:** Demo + review with stakeholders
- **Issues:** Immediate communication via Slack/email
- **Final:** Post-implementation review + lessons learned

---

## Open Questions (To Be Resolved Before Implementation)

### 1. Should we cache generated schemas?
**Impact:** Performance optimization
**Decision needed:** Yes/No, if yes: cache size, TTL, invalidation strategy
**Owner:** TBD
**Deadline:** Before Phase 1 complete

### 2. How to handle schema evolution over time?
**Impact:** Backward compatibility, migrations
**Decision needed:** Versioning strategy, migration tooling
**Owner:** TBD
**Deadline:** Before Phase 4 (schema migration)

### 3. Do we support multiple providers with different constraints?
**Impact:** Architecture (generic vs provider-specific)
**Decision needed:** Abstract validation or OpenAI-only for now
**Owner:** TBD
**Deadline:** Before Phase 1 complete

### 4. What's the schema size limit?
**Impact:** Error handling, warnings
**Decision needed:** Token limit threshold, how to enforce
**Owner:** TBD
**Deadline:** Before Phase 2 (codec update)

---

## Timeline and Milestones

```
Week 1:
  Mon-Thu: Phase 1 (SchemaBuilder + FormatBuilder)
  Fri:     Review + adjust

Week 2:
  Mon-Wed: Phase 2 (Codec update)
  Thu-Fri: Phase 3 start (Section composition)

Week 3:
  Mon-Wed: Phase 3 complete
  Thu-Fri: Phase 4 start (Schema audit + migration planning)

Week 4:
  Mon-Thu: Phase 4 continue (Schema migration)
  Fri:     Phase 5 (Cleanup)

Week 5:
  Mon-Tue: Documentation + final review
  Wed:     Deploy to staging
  Thu-Fri: Monitor staging

Week 6:
  Mon:     Deploy canary (10%)
  Wed:     Increase to 50%
  Fri:     Increase to 100%

Week 7:
  Mon-Fri: Monitor production

Week 8:
  Mon:     Post-implementation review
  Tue:     Final cleanup + close
```

**Total Duration:** 6-8 weeks (including monitoring and gradual rollout)

---

## Checklist for Implementation Start

### Before Writing Code
- [ ] All planning documents reviewed and approved
- [ ] Open questions resolved
- [ ] Stakeholders briefed
- [ ] Test strategy agreed upon
- [ ] Rollout plan agreed upon
- [ ] Feature flag infrastructure ready (if needed)

### Before Phase 1
- [ ] Create feature branch from `orchestrai_v0.4.0`
- [ ] Set up test fixtures directory
- [ ] Configure coverage tools
- [ ] Write test data fixtures

### Before Each Phase
- [ ] Review phase plan
- [ ] Identify dependencies
- [ ] Set up monitoring (if applicable)
- [ ] Write tests FIRST (TDD)

### Before Merge
- [ ] All tests pass
- [ ] Coverage thresholds met
- [ ] Code reviewed by 2+ engineers
- [ ] Documentation updated
- [ ] Changelog entry added

### Before Deploy
- [ ] Staging tests pass
- [ ] Performance benchmarks acceptable
- [ ] Rollback plan tested
- [ ] Alerts configured
- [ ] Stakeholders notified

---

## Final Notes

**This is a PLAN document.** No code changes have been made yet.

**Next steps:**
1. Review this plan with the team
2. Resolve open questions
3. Get approval to proceed
4. Create implementation branch
5. Begin Phase 1

**Questions or concerns?** Raise them before implementation starts.

**Estimated effort:** 15-20 developer-days of focused work + 2-3 weeks monitoring

**Confidence level:** High (90%+) based on:
- Clear understanding of current state (comprehensive audit)
- Validated OpenAI API constraints (official docs + community confirmation)
- Existing proof of concept (MetafieldItem already works with nested unions)
- Comprehensive test plan (minimal unknowns)
- Low-risk rollout strategy (gradual, monitored)

---

## Appendix: Quick Reference

### Key Files to Create
```
orchestrai/schemas/
├── __init__.py
├── builder.py              # SchemaBuilder
├── format_builder.py       # FormatBuilder
├── exceptions.py           # SchemaValidationError
└── registry.py             # SectionRegistry

tests/orchestrai/schemas/
├── test_schema_builder.py
├── test_format_builder.py
├── test_schema_validation.py
└── test_section_composition.py
```

### Key Files to Modify
```
orchestrai/contrib/provider_codecs/openai/responses_json.py  # Use new pipeline
orchestrai/contrib/provider_backends/openai/schema_adapters.py  # Delete FlattenUnions
```

### Key Files to Delete (Phase 5)
```
orchestrai/contrib/provider_backends/openai/schema_adapters.py:24-66  # FlattenUnions class
orchestrai/contrib/provider_backends/openai/schema_adapters.py:69-97  # OpenaiWrapper class (move to FormatBuilder)
```

### Documentation Files
```
docs/
├── openai_schema_notes.md           # ✅ Created
├── schema_workflow_map.md           # ✅ Created
├── schema_pipeline_architecture.md  # ✅ Created
├── flatten_unions_evaluation.md     # ✅ Created
├── test_coverage_plan.md            # ✅ Created
└── IMPLEMENTATION_PLAN.md           # ✅ Created (this file)
```

---

**End of Implementation Plan**

**Status:** READY FOR REVIEW
**Date:** 2026-01-02
**Author:** Claude Code
**Reviewers:** [TBD]
**Approvers:** [TBD]
