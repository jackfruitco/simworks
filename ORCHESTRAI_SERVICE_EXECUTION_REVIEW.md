# OrchestrAI Service Execution Lifecycle Review: OpenAI Responses API + Structured Outputs

**Branch**: `claude/review-service-execution-5psO9`
**Base**: `origin/orchestrai_v0.4.0`
**Date**: 2026-01-02
**Reviewer**: Claude (Sonnet 4.5)

---

## 1. Execution Lifecycle Map

### Primary Execution Path (Async)

```
Entry Point: BaseService.task.arun() or BaseService.execute()
  └─> LifecycleMixin.aexecute()
      ├─> setup(context)                                    [service.py:422-429]
      ├─> arun(**ctx) → _arun_core(stream=False)            [service.py:1292-1299, 1301-1464]
      │   ├─> ServiceCall creation/resolution               [service.py:1315-1333]
      │   ├─> resolve_call_client()                         [service.py:1339-1350]
      │   ├─> aprepare(stream=False)                        [service.py:984-1053]
      │   │   ├─> _aprepare_codec()                         [service.py:917-982]
      │   │   │   └─> _select_codec_class()                 [service.py:824-882]
      │   │   │       └─> resolve_codec(...)                [resolve/codec.py:51-122]
      │   │   │           └─> constraint matching           [codec.py:103-120]
      │   │   ├─> abuild_request()                          [service.py:1058-1121]
      │   │   │   ├─> aget_prompt()                         [service.py:604-639]
      │   │   │   │   └─> _aget_prompt()                    [service.py:641-766]
      │   │   │   │       ├─> _resolve_prompt_plan()        [service.py:572-602]
      │   │   │   │       │   └─> resolve_prompt_plan()     [resolve/prompt_plan.py:25-73]
      │   │   │   │       └─> PromptEngine.abuild_from()
      │   │   │   ├─> _abuild_request_instructions()        [service.py:1149-1158]
      │   │   │   ├─> _abuild_request_user_input()          [service.py:1160-1169]
      │   │   │   ├─> _abuild_request_extras()              [service.py:1171-1194]
      │   │   │   └─> _afinalize_request()                  [service.py:1196-1204]
      │   │   └─> _attach_response_schema_to_request()      [service.py:884-913]
      │   │       └─> apply_schema_adapters() ❌ BUG        [service.py:903, resolve/schema.py:17-39]
      │   ├─> codec.asetup(context)                         [service.py:1399-1404]
      │   ├─> codec.aencode(req) ⚠️ CRITICAL                [service.py:1406-1410]
      │   │   └─> OpenAIResponsesJsonCodec.aencode()        [responses_json.py:73-139]
      │   │       ├─> schema_cls.model_json_schema()        [responses_json.py:96]
      │   │       ├─> FlattenUnions.adapt()                 [schema_adapters.py:38-66]
      │   │       ├─> OpenaiWrapper.adapt()                 [schema_adapters.py:89-97]
      │   │       ├─> req.response_schema_json = compiled   [responses_json.py:134]
      │   │       └─> req.provider_response_format = compiled [responses_json.py:135]
      │   ├─> emitter.emit_request()                        [service.py:1432-1436]
      │   └─> _asend(client, req, codec, attrs, ident)      [service.py:1466-1597]
      │       ├─> client.send_request(req)                  [client/client.py:35-188]
      │       │   └─> provider.call(req, timeout)           [client/client.py:119]
      │       │       └─> OpenAIResponsesProvider.call()    [openai/openai.py:99-132]
      │       │           ├─> build_responses_request() ❌ P0 BUG [request_builder.py:81-149]
      │       │           │   └─> payload["text"] = response_format  ❌ WRONG FIELD
      │       │           └─> client.responses.create(**payload)    [openai.py:131]
      │       ├─> codec.adecode(resp)                       [service.py:1546-1550]
      │       │   └─> OpenAIResponsesJsonCodec.adecode()    [responses_json.py:140-192]
      │       │       ├─> extract_structured_candidate()    [codec.py:337-366]
      │       │       └─> schema_cls.model_validate()       [responses_json.py:181]
      │       ├─> resp.structured_data = validated          [service.py:1550]
      │       ├─> emitter.emit_response()                   [service.py:1552]
      │       ├─> on_success(context, resp)                 [service.py:1553]
      │       └─> codec.ateardown()                         [service.py:1592-1596]
      ├─> teardown()                                        [service.py:431-433]
      └─> finalize(result)                                  [service.py:435-437]
```

### Resolution Order

#### 1. Schema Resolution (at `__init__`)
```
packages/orchestrai/src/orchestrai/resolve/schema.py:42-105

Precedence:
  1. Override (passed to __init__ as response_schema)
  2. Class default (BaseService.response_schema)
  3. Registry lookup (by service identity → schema identity transform)
  4. None

Schema adapters applied ONLY if provided explicitly to resolve_schema()
❌ BUG: _attach_response_schema_to_request re-applies adapters AFTER codec.aencode
```

#### 2. Codec Resolution (at `aprepare`)
```
packages/orchestrai/src/orchestrai/resolve/codec.py:51-122

Precedence:
  1. Override (_codec_override, from codec= at __init__)
  2. Explicit (codec_cls arg or BaseService.codec_cls)
  3. Configured (BaseService.codecs list)
  4. Registry match (constraint-based: provider, api, result_type)
  5. None

Constraint matching uses BaseCodec.matches(provider=..., api=..., result_type=...)
```

#### 3. Prompt Plan Resolution (at `_aget_prompt`)
```
packages/orchestrai/src/orchestrai/resolve/prompt_plan.py:25-73

Precedence:
  1. Explicit (_prompt_plan from __init__ or class default)
  2. Registry (PromptSection with identity matching service identity)
  3. None
```

---

## 2. Ranked Bug List

### P0 (Critical - Breaks Production)

#### **BUG-001: Wrong API Field Name in OpenAI Request Builder**
- **Location**: `packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/request_builder.py:139`
- **Symptom**: OpenAI Responses API calls fail with 400 Bad Request or ignore structured outputs entirely
- **Root Cause**:
  ```python
  payload = {
      "model": model,
      "input": ...,
      "text": resolved_response_format,  # ❌ WRONG FIELD NAME
  }
  ```
  The OpenAI Responses API does NOT accept a `text` field for structured outputs. Based on OpenAI's SDK and API patterns, structured outputs should be passed via `response_format` parameter.

- **Fix**: Replace `"text"` with the correct field name for OpenAI Responses API structured outputs
- **Impact**: All services using structured outputs with OpenAI Responses API are broken
- **Evidence**:
  - Line 139 uses `"text": resolved_response_format`
  - `resolved_response_format` contains the wrapped schema: `{"type": "json_schema", "json_schema": {...}}`
  - This wrapper format matches OpenAI's expected `response_format` structure, not a `text` parameter

---

### P1 (High - Data Integrity Issues)

#### **BUG-002: Double Schema Adaptation in Two Different Code Paths**
- **Location**:
  - First: `service.py:903` → `resolve/schema.py:65, 75, 100` (via `_attach_response_schema_to_request`)
  - Second: `responses_json.py:118-129` (via `codec.aencode`)
- **Symptom**: Schema adapters (FlattenUnions, OpenaiWrapper) run twice, causing:
  - Double-wrapping: `{"type": "json_schema", "json_schema": {"type": "json_schema", "json_schema": {...}}}`
  - Invalid JSON schema sent to OpenAI
- **Root Cause**:
  1. `BaseService.__init__` calls `resolve_schema()` which applies adapters (lines 225-233)
  2. Later, `_attach_response_schema_to_request()` re-applies adapters if codec is present (line 903)
  3. Then, `codec.aencode()` applies its own adapters (responses_json.py:120-129)

- **Fix**: Remove adapter application from `_attach_response_schema_to_request()`. Codec should be sole owner of schema adaptation.
- **Impact**: Schemas are malformed when sent to OpenAI, causing validation failures or unexpected behavior

#### **BUG-003: Schema Adaptation Runs AFTER Codec Encode**
- **Location**: `service.py:1033` → `_attach_response_schema_to_request()` called AFTER `codec.aencode()` at line 1410
- **Symptom**: Codec's schema adaptation is overwritten by service's late attachment
- **Root Cause**: Execution order in `aprepare()`:
  ```python
  async def aprepare(...):
      codec, codec_label = await self._aprepare_codec()  # 1008
      req = await self.abuild_request(**kwargs)          # 1028
      req.stream = bool(stream)                          # 1029
      self._attach_response_schema_to_request(req, codec)  # 1033 ← LATE
  ```
  But then in `_arun_core()`:
  ```python
  req, codec, attrs = await self.aprepare(...)  # 1394
  await codec.aencode(req)                      # 1410 ← RUNS AFTER
  ```

- **Fix**: Remove `_attach_response_schema_to_request()` entirely or ensure it only sets `req.response_schema`, not schema JSON or provider format
- **Impact**: Codec's work is silently overwritten, breaking custom schema adaptation logic

---

### P1 (High - Missing Critical Metadata)

#### **BUG-004: Response Object Missing Required Metadata for Persistence/WebSocket**
- **Location**: `service.py:1531-1553` (response post-processing in `_asend`)
- **Symptom**: Response object lacks critical fields needed for:
  - Database persistence (ServiceCallRecord)
  - WebSocket push (requires full audit trail)
  - Debugging/tracing

- **Missing Fields**:
  - ✅ `namespace, kind, name` (set at 1532)
  - ✅ `request_correlation_id` (set at 1534)
  - ✅ `codec_identity` (attempted at 1539, may fail)
  - ❌ **Service identity** (not set)
  - ❌ **Prompt identity / prompt plan source** (not set)
  - ❌ **Schema identity** (not set)
  - ❌ **Model name** (set by provider, but not always)
  - ❌ **Token usage** (set by provider, but may be incomplete)
  - ❌ **Trace IDs / correlation IDs** for distributed tracing
  - ❌ **Request payload snapshot** (for audit/replay)

- **Root Cause**: Response object is a minimal DTO; no explicit "audit envelope" or "response metadata" gathering step
- **Fix**:
  1. Add `ResponseMetadata` helper to collect all execution context
  2. Stamp it onto `resp.execution_metadata` or `resp.provider_meta["orchestrai"]`
  3. Include: service identity, prompt source, schema identity, codec identity, model, timing, context snapshot

- **Impact**: Cannot reliably persist or broadcast responses; missing data for debugging production issues

---

### P2 (Medium - Inconsistencies & Foot-Guns)

#### **BUG-005: Inconsistent Codec Schema Source Resolution**
- **Location**: `codec.py:88-99` (`_get_schema_from_service`) vs `responses_json.py:162-172` (`adecode`)
- **Symptom**: Different code paths use different fallback chains for finding the schema
- **Root Cause**:
  - `BaseCodec._get_schema_from_service()`: `service.response_schema` OR None
  - `OpenAIResponsesJsonCodec.adecode()`: `resp.request.response_schema` → `service.response_schema` → `self.response_schema`

- **Fix**: Standardize to a single schema resolution helper in BaseCodec
- **Impact**: Decode may work in some cases where encode fails, or vice versa; inconsistent behavior

#### **BUG-006: Silent Failure in codec_identity Propagation**
- **Location**: `service.py:1537-1544`
- **Symptom**: Codec identity attachment to response fails silently; no logging, just `logger.debug`
- **Root Cause**:
  ```python
  try:
      resp.codec_identity = req.codec_identity
  except Exception:
      logger.debug("failed to propagate codec_identity to response", exc_info=True)
  ```

- **Fix**: Ensure `Response` type has `codec_identity` field, or raise error if critical
- **Impact**: Response objects may lack codec identity, breaking later decoding or audit trails

#### **BUG-007: Schema Adapter Ordering Ambiguity**
- **Location**: `responses_json.py:68-71` vs `schema_adapters.py:36, 87`
- **Symptom**: Adapters are manually ordered in codec class; if new adapters are added, ordering is fragile
- **Root Cause**:
  ```python
  schema_adapters: ClassVar[Sequence[BaseSchemaAdapter]] = (
      FlattenUnions(order=0),
      OpenaiWrapper(order=999)
  )
  ```
  Relies on explicit `order` values; no automatic sorting or validation

- **Fix**: Sort adapters by `order` field in `BaseCodec.__init_subclass__` (already done at codec.py:68-70, but fragile)
- **Impact**: If order is wrong, schema may be double-wrapped or unions not flattened

#### **BUG-008: No Validation That Schema Matches Codec Constraints**
- **Location**: Codec selection (resolve/codec.py) vs Schema resolution (resolve/schema.py) are independent
- **Symptom**: Service may select a codec for "openai.responses.json" but use a schema not compatible with JSON Schema
- **Root Cause**: No cross-validation between codec selection and schema resolution
- **Fix**: Add validation step after codec selection to ensure schema is compatible
- **Impact**: Runtime errors when codec tries to encode incompatible schema

---

### P2 (Medium - Missing Error Handling)

#### **BUG-009: Codec Decode Failures Are Non-Retriable But May Be Transient**
- **Location**: `service.py:1562-1570`
- **Symptom**: Codec validation errors (CodecDecodeError) immediately fail the service call, even if retries might succeed
- **Root Cause**:
  ```python
  except CodecDecodeError as e:
      # Validation failures are non-retriable - fail immediately
      self.emitter.emit_failure(...)
      await self.on_failure(context, e)
      logger.error("llm.service.validation_failed", ...)
      raise
  ```

- **Fix**: Distinguish between:
  - Schema mismatch (non-retriable)
  - Malformed JSON from provider (potentially retriable)
  - Validation errors due to incomplete responses (potentially retriable)

- **Impact**: Transient provider issues (truncated JSON) cause permanent failures instead of retries

---

### P2 (Medium - Legacy/Cleanup)

#### **BUG-010: `_attach_response_schema_to_request` Has Dead Code Path**
- **Location**: `service.py:884-913`
- **Symptom**: Function tries to adapt schema if codec is present, but this is redundant with codec.aencode()
- **Root Cause**: Legacy code that predates codec-owned schema adaptation
- **Fix**: Remove the entire function; codec.aencode() should be the sole schema adapter
- **Impact**: Maintenance burden; confusing execution flow

---

### P3 (Low - Quality of Life)

#### **BUG-011: Excessive Logging in Request Builder**
- **Location**: `request_builder.py:108-117, 142`
- **Symptom**: Debug logs spam production logs
- **Fix**: Remove or gate behind `log_prompts` flag
- **Impact**: Log noise

#### **BUG-012: Metadata Field Uses JSON String Instead of Dict**
- **Location**: `request_builder.py:144-146`
- **Symptom**: OpenAI metadata is sent as `{"orchestrai": "{\"codec_identity\": \"...\"}"}`
- **Root Cause**:
  ```python
  payload["metadata"] = {"orchestrai": json.dumps(metadata)}
  ```

- **Fix**: Verify if OpenAI actually requires a string; if not, pass dict directly
- **Impact**: Harder to parse metadata in OpenAI dashboard/logs

---

## 3. Patch Plan

### Phase 1: Critical Fixes (P0)

#### Patch 1.1: Fix OpenAI Request Field Name
**Files**: `request_builder.py`

**Change**:
```python
# OLD (line 139)
payload = {
    ...
    "text": resolved_response_format,
}

# NEW
payload = {
    ...
    "response_format": resolved_response_format,  # Correct field name for OpenAI Responses API
}
```

**Test**:
```python
def test_build_responses_request_uses_correct_field_for_structured_output():
    req = Request(input=[], response_schema_json={"type": "object"})
    wrapped = {"type": "json_schema", "json_schema": {"name": "response", "schema": {"type": "object"}}}

    payload = build_responses_request(
        req=req,
        model="gpt-4o-mini",
        response_format=wrapped,
    )

    assert "response_format" in payload
    assert payload["response_format"] == wrapped
    assert "text" not in payload  # Ensure old field is gone
```

---

### Phase 2: High-Priority Fixes (P1)

#### Patch 2.1: Remove Double Schema Adaptation
**Files**: `service.py`, `resolve/schema.py`

**Changes**:
1. Remove adapter application from `_attach_response_schema_to_request`:
   ```python
   def _attach_response_schema_to_request(self, req: Request, codec: BaseCodec | None = None) -> None:
       schema_cls = self.response_schema
       if schema_cls is None:
           return

       if getattr(req, "response_schema", None) is None:
           req.response_schema = schema_cls

       # ❌ REMOVE THIS BLOCK (lines 894-906)
       # schema_json = self._resolved_schema_json
       # if schema_json is None:
       #     try:
       #         schema_json = schema_cls.model_json_schema()
       #     except Exception:
       #         schema_json = None
       #
       # if codec is not None and getattr(codec, "schema_adapters", None):
       #     try:
       #         schema_json = apply_schema_adapters(schema_cls, getattr(codec, "schema_adapters"))
       #     except Exception:
       #         logger.debug("schema adapter application failed", exc_info=True)
       #
       # if schema_json is None:
       #     return
       #
       # req.response_schema_json = schema_json
       # if getattr(req, "provider_response_format", None) is None:
       #     req.provider_response_format = schema_json
   ```

2. Remove adapter application from `resolve_schema`:
   ```python
   # OLD (lines 65, 75, 100)
   branch.meta["schema_json"] = apply_schema_adapters(override, adapters or ())

   # NEW
   branch.meta["schema_json"] = None  # Codecs will adapt schemas, not resolvers
   ```

**Test**:
```python
@pytest.mark.asyncio
async def test_schema_adapters_run_only_once():
    adapter_call_count = 0

    class CountingAdapter:
        order = 0
        def adapt(self, schema):
            nonlocal adapter_call_count
            adapter_call_count += 1
            return schema

    class TestCodec(BaseCodec):
        schema_adapters = [CountingAdapter()]

    class TestService(BaseService):
        response_schema = SomeSchema

    service = TestService()
    req, codec, _ = await service.aprepare(stream=False)

    await codec.aencode(req)

    assert adapter_call_count == 2  # FlattenUnions + OpenaiWrapper, not 4 or 6
```

#### Patch 2.2: Add Response Metadata Collection
**Files**: `service.py`, `types/transport.py`

**Changes**:
1. Add metadata field to Response:
   ```python
   class Response(StrictBaseModel):
       ...
       execution_metadata: dict[str, Any] = Field(default_factory=dict)
   ```

2. Collect metadata in `_asend`:
   ```python
   # After line 1531 (inside try block after resp = await client.send_request(req))
   execution_meta = {
       "service_identity": ident.as_str,
       "prompt_plan_source": self.context.get("prompt.plan.source"),
       "schema_identity": getattr(self.response_schema, "identity", None),
       "codec_identity": req.codec_identity,
       "model": req.model,
       "request_correlation_id": str(req.correlation_id),
       "timestamp": datetime.utcnow().isoformat(),
   }
   resp.execution_metadata.update(execution_meta)
   ```

**Test**:
```python
def test_response_includes_execution_metadata(mock_client):
    service = TestService()
    resp = await service._asend(mock_client, req, codec, attrs, ident)

    assert "service_identity" in resp.execution_metadata
    assert resp.execution_metadata["service_identity"] == "services.test.svc.test"
    assert "prompt_plan_source" in resp.execution_metadata
    assert "schema_identity" in resp.execution_metadata
```

---

### Phase 3: Medium-Priority Fixes (P2)

#### Patch 3.1: Standardize Codec Schema Resolution
**Files**: `codec.py`, `responses_json.py`

**Change**: Update `BaseCodec._get_schema_from_service` to match `OpenAIResponsesJsonCodec.adecode` fallback chain

**Test**: Unit tests for schema resolution in different scenarios

#### Patch 3.2: Add codec_identity to Response Type
**Files**: `types/transport.py`

**Change**:
```python
class Response(StrictBaseModel):
    ...
    codec_identity: str | None = None  # Add explicit field
```

---

## 4. Golden Path Contract

### Request Object (Before Provider Call)

**Required Fields**:
```python
{
    "model": "gpt-4o-mini",                    # ✅ Set by service or client
    "input": [                                  # ✅ Built by service.abuild_request()
        {"role": "developer", "content": [...]},
        {"role": "user", "content": [...]}
    ],
    "namespace": "simulation",                 # ✅ Set by service (from identity)
    "kind": "svc",                              # ✅ Set by service (from identity)
    "name": "feedback",                         # ✅ Set by service (from identity)
    "correlation_id": UUID("..."),              # ✅ Auto-generated
    "response_schema": HotwashInitialSchema,    # ✅ Resolved at __init__
    "response_schema_json": {...},              # ✅ Set by codec.aencode()
    "provider_response_format": {               # ✅ Set by codec.aencode()
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "schema": {/* flattened, adapted schema */}
        }
    },
    "codec_identity": "openai.responses.json",  # ✅ Set by service.aprepare()
    "stream": false,                            # ✅ Set by service.aprepare()
    "temperature": 0.2,                         # ✅ Default or override
    "max_output_tokens": null | int,            # ✅ Optional
    "tools": [],                                # ✅ Optional
    "tool_choice": "auto",                      # ✅ Default
}
```

### Provider Payload (OpenAI Responses API)

**Generated by**: `build_responses_request()`

```python
{
    "model": "gpt-4o-mini",
    "input": [/* normalized messages */],
    "response_format": {  # ❌ CURRENTLY "text" (BUG-001)
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "schema": {/* JSON Schema */}
        }
    },
    "previous_response_id": null,
    "tools": null | [/* tool defs */],
    "tool_choice": "auto",
    "max_output_tokens": null | int,
    "timeout": 30.0,
    "metadata": {
        "orchestrai": "{\"codec_identity\": \"...\", \"tools_declared\": [...]}"
    }
}
```

### Response Object (After Decode)

**Complete Response**:
```python
{
    # Identity (echoed from service)
    "namespace": "simulation",
    "kind": "svc",
    "name": "feedback",

    # Correlation
    "correlation_id": UUID("..."),               # Response ID
    "request_correlation_id": UUID("..."),       # Request ID

    # Request snapshot
    "request": Request(...),                     # Full request object

    # Provider/timing
    "provider_name": "openai",
    "client_name": "default",
    "received_at": datetime(...),

    # Output
    "output": [                                  # Normalized output items
        {
            "role": "assistant",
            "content": [
                {"type": "output_text", "text": "..."}
            ]
        }
    ],

    # Usage
    "usage": {
        "input_tokens": 150,
        "output_tokens": 200,
        "total_tokens": 350
    },

    # Structured output (validated Pydantic model)
    "structured_data": HotwashInitialSchema(...),

    # Provider metadata
    "provider_meta": {
        "model": "gpt-4o-mini-2024-07-18",
        "id": "resp_abc123",
        "raw": {/* full provider response */}
    },

    # ❌ MISSING: Execution metadata (BUG-004)
    "execution_metadata": {  # Should include:
        "service_identity": "services.simulation.svc.feedback",
        "prompt_plan_source": "registry",
        "schema_identity": "schemas.simulation.schema.hotwash_initial",
        "codec_identity": "codecs.openai.responses.json",
        "model": "gpt-4o-mini",
        "timestamp": "2026-01-02T12:34:56.789Z",
        "trace_id": "...",  # If distributed tracing enabled
    },

    # Codec identity
    "codec_identity": "openai.responses.json",  # ❌ May be missing (BUG-006)
}
```

### Persistence/WebSocket Requirements

**For Database (ServiceCallRecord)**:
```python
{
    "id": call.id,
    "service_identity": "services.simulation.svc.feedback",
    "status": "succeeded" | "failed",
    "input": {/* original context/payload */},
    "context": {/* execution context snapshot */},
    "result": Response(...),  # Full response object
    "error": null | "...",
    "dispatch": {"service": "...", "runner": "inline"},
    "created_at": datetime(...),
    "started_at": datetime(...),
    "finished_at": datetime(...),
}
```

**For WebSocket Push**:
```python
{
    "event": "ai_response_ready",
    "payload": {
        "call_id": "...",
        "service": "services.simulation.svc.feedback",
        "correlation_id": "...",
        "structured_data": {/* validated model dict */},
        "metadata": {
            "model": "gpt-4o-mini",
            "tokens": 350,
            "execution_time_ms": 1234,
        }
    }
}
```

---

## Summary

**Total Bugs Found**: 12
**P0 (Critical)**: 1
**P1 (High)**: 3
**P2 (Medium)**: 5
**P3 (Low)**: 3

**Most Critical Issue**: BUG-001 (Wrong API field name) completely breaks OpenAI Responses API structured outputs.

**Recommended Fix Order**:
1. Patch 1.1 (BUG-001): Fix field name → enables basic structured output
2. Patch 2.1 (BUG-002, BUG-003): Remove double adaptation → fixes schema corruption
3. Patch 2.2 (BUG-004): Add metadata → enables persistence/websocket
4. Remaining P2/P3 as time permits

**Test Coverage**:
- Unit tests for request builder (field names, schema wrapping)
- Integration tests for full service execution with structured outputs
- End-to-end tests with mock OpenAI client
- Regression tests for schema adaptation order

**Documentation Needed**:
- Architecture doc explaining codec vs service schema ownership
- Migration guide for any breaking changes
- Runbook for debugging structured output failures
