# Schema Workflow Map - Current Implementation (orchestrai_v0.4.0)

## Overview

This document maps the **complete end-to-end schema workflow** in SimWorks/OrchestrAI, from schema definition through API dispatch to response parsing and persistence.

## High-Level Flow

```
[1. Schema Definition]
    ↓
[2. Schema Registration]
    ↓
[3. Service Declaration]
    ↓
[4. Request Build]
    ↓
[5. Codec Encoding]
    ↓
[6. Schema Adaptation]
    ↓
[7. Provider Request Build]
    ↓
[8. OpenAI API Call]
    ↓
[9. Response Reception]
    ↓
[10. Codec Decoding]
    ↓
[11. Validation/Parsing]
    ↓
[12. Persistence]
```

---

## 1. Schema Definition

### Base Classes

**Core Pydantic Base:**
- **File:** `packages/orchestrai/src/orchestrai/types/base.py:9-21`
- **Class:** `StrictBaseModel`
- **Config:** `extra="forbid"`, `populate_by_name=True`
- **Purpose:** Foundation for all strict models

**OrchestrAI Schema Base:**
- **File:** `packages/orchestrai/src/orchestrai/components/schemas/base.py:10-21`
- **Classes:**
  - `BaseOutputItem` - for individual output elements
  - `BaseOutputSchema` - for complete output schemas
- **Features:**
  - Inherits from `StrictBaseModel`
  - Includes `IdentityMixin` for registry integration
  - Domain: `SCHEMAS_DOMAIN`

**Django Schema Base:**
- **File:** `packages/orchestrai_django/src/orchestrai_django/components/schemas/types.py` (inferred)
- **Class:** `DjangoBaseOutputSchema`
- **Purpose:** Django-aware schemas with persistence hooks

### Example Schema Definitions

**SimWorks Chatlab Patient Schemas:**
- **File:** `SimWorks/chatlab/orca/schemas/patient.py`
- **Schemas:**
  - `PatientInitialOutputSchema` - initial patient response
  - `PatientReplyOutputSchema` - subsequent replies
  - `PatientResultsOutputSchema` - final results payload
- **Pattern:**
  - Use `@schema` decorator
  - Mix in domain-specific mixins (`ChatlabMixin`, `StandardizedPatientMixin`)
  - Declare structured fields with Pydantic Field validators
  - Include metadata sections, messages, condition checks

**SimWorks Simulation Feedback Schema:**
- **File:** `SimWorks/simulation/orca/schemas/feedback.py`
- **Schema:** `HotwashInitialSchema`
- **Fields:**
  - `llm_conditions_check` - conditions validation items
  - `metadata` - feedback metadata block

**Metadata Types (Discriminated Unions):**
- **File:** `SimWorks/chatlab/orca/types/metadata.py:90-105`
- **Type:** `MetafieldItem`
- **Pattern:** TypeAlias with `Union` + `Field(discriminator="kind")`
- **Variants:**
  - `GenericMetafield`
  - `LabResultMetafield`
  - `RadResultMetafield`
  - `PatientHistoryMetafield`
  - `PatientDemographicsMetafield`
  - `SimulationMetafield`
  - `ScenarioMetafield`
  - Various feedback metafields

**IMPORTANT FINDING:** The `MetafieldItem` union uses a **discriminated union** pattern which generates `anyOf` at the **field level**, not root level. This is supported by OpenAI.

---

## 2. Schema Registration

### Decorator-Based Registration

**Schema Decorator:**
- **File:** `packages/orchestrai/src/orchestrai/decorators/components/schema_decorator.py` (inferred from imports)
- **Usage:** `@schema` decorator on schema classes
- **Effect:**
  - Registers schema in global `ComponentStore`
  - Assigns identity (namespace/kind/name)
  - Makes schema discoverable via identity lookups

**Example:**
```python
@schema
class PatientInitialOutputSchema(ChatlabMixin, StandardizedPatientMixin, DjangoBaseOutputSchema):
    # Schema definition
    pass
```

### Component Store

**Registry:**
- **File:** `packages/orchestrai/src/orchestrai/registry/active_app.py` (inferred)
- **Function:** `get_component_store()`
- **Purpose:** Central registry for all components (schemas, services, codecs, etc.)
- **Lookup:** By domain + identity

---

## 3. Service Declaration

### Service Base Classes

**Core Service:**
- **File:** `packages/orchestrai/src/orchestrai/components/services/service.py` (inferred)
- **Class:** `BaseService`

**Django Service:**
- **File:** `packages/orchestrai_django/src/orchestrai_django/components/services/` (inferred)
- **Class:** `DjangoBaseService`

### Schema Attachment to Services

**Pattern 1: Class-level `response_schema`**
```python
@service
class GenerateInitialResponse(DjangoBaseService):
    from chatlab.orca.schemas import PatientInitialOutputSchema as _Schema
    response_schema = _Schema  # Attached here
```
**File:** `SimWorks/chatlab/orca/services/patient.py:26-36`

**Pattern 2: Runtime schema resolution**
```python
async def build_messages_and_schema(self, ...) -> Tuple[List[DjangoInputItem], Optional[Type[Schema]]]:
    # Service method returns schema dynamically
    return msgs, self.response_format_cls
```
**File:** `SimWorks/chatlab/orca/services/patient.py:66-85`

**Schema Resolution:**
- **File:** `packages/orchestrai/src/orchestrai/resolve/schema.py:42-112`
- **Function:** `resolve_schema()`
- **Precedence:**
  1. `override` parameter (highest)
  2. `default` parameter (class-level)
  3. ComponentStore lookup by identity
  4. None (no schema)
- **IMPORTANT:** Schema adapters are **NOT** applied here (codec responsibility)

---

## 4. Request Build

### Request Types

**Core Request:**
- **File:** `packages/orchestrai/src/orchestrai/types/transport.py` (inferred)
- **Class:** `Request`
- **Schema Fields:**
  - `response_schema` - Pydantic model class
  - `response_schema_json` - dict (set by codec)
  - `provider_response_format` - backend-specific payload (set by codec)
  - `codec_identity` - identity of codec to use

**Django Request:**
- **File:** `packages/orchestrai_django/src/orchestrai_django/types/django_dtos.py:74-92`
- **Class:** `DjangoRequest`
- **Additional Fields:**
  - `object_db_pk` - foreign key to domain object
  - `context` - service/app context
  - `messages_rich` - rich message DTOs
  - `prompt_meta` - prompt metadata

### Service → Request

Services build `Request` objects with:
1. Model name
2. Input messages
3. `response_schema` (Pydantic class)
4. Context metadata
5. Tools (if applicable)

---

## 5. Codec Encoding

### Codec System

**Base Codec:**
- **File:** `packages/orchestrai/src/orchestrai/components/codecs/codec.py` (inferred)
- **Class:** `BaseCodec`
- **Methods:**
  - `encode()` / `aencode()` - attach backend-specific schema format to Request
  - `decode()` / `adecode()` - parse Response into schema instance

**OpenAI Responses JSON Codec:**
- **File:** `packages/orchestrai/src/orchestrai/contrib/provider_codecs/openai/responses_json.py`
- **Class:** `OpenAIResponsesJsonCodec`
- **Identity:** namespace="openai", kind="responses", name="json"
- **Decorator:** `@codec(name="json")`

### Encoding Flow

**File:** `packages/orchestrai/src/orchestrai/contrib/provider_codecs/openai/responses_json.py:73-128`

**Steps:**
1. **Extract base schema:**
   - Prefer `req.response_schema.model_json_schema()`
   - Fallback to `req.response_schema_json`
   - If neither present, return (no structured output)

2. **Apply schema adapters:**
   - Run through ordered list: `self.schema_adapters`
   - Current adapters:
     - `FlattenUnions(order=0)` - flatten oneOf unions
     - `OpenaiWrapper(order=999)` - wrap in OpenAI format

3. **Store results:**
   - `req.response_schema_json` = adapted schema (for diagnostics)
   - `req.provider_response_format` = backend-ready payload

**Key Code:**
```python
base_schema = source.model_json_schema()  # From Pydantic model
compiled = base_schema
for adapter in self.schema_adapters:
    compiled = adapter.adapt(compiled)
req.response_schema_json = compiled
setattr(req, "provider_response_format", compiled)
```

---

## 6. Schema Adaptation

### Current Adapters

**Base Adapter:**
- **File:** `packages/orchestrai/src/orchestrai/components/schemas/adapters.py` (inferred)
- **Class:** `BaseSchemaAdapter`
- **Method:** `adapt(schema: dict) -> dict`
- **Ordering:** `order` attribute determines execution sequence

**OpenAI Base Adapter:**
- **File:** `packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/schema_adapters.py:19-21`
- **Class:** `OpenaiBaseSchemaAdapter`
- **Provider:** `"openai-prod"`

### FlattenUnions Adapter

**File:** `packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/schema_adapters.py:24-66`

**Purpose:** Flatten `oneOf` unions because OpenAI doesn't support union types

**Order:** 0 (runs first)

**Algorithm:**
1. Recursively walk schema tree
2. Find any `oneOf` nodes
3. Merge all variant properties into single object
4. Remove `oneOf` key
5. Set `type: "object"`
6. Merge properties
7. Add warning to description

**Code:**
```python
def adapt(self, schema: Dict[str, Any]) -> Dict[str, Any]:
    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            for k, v in list(node.items()):
                node[k] = walk(v)
            one = node.get("oneOf")
            if isinstance(one, list):
                merged_props: Dict[str, Any] = {}
                for variant in one:
                    if isinstance(variant, dict):
                        merged_props.update(variant.get("properties", {}))
                node.pop("oneOf", None)
                node["type"] = "object"
                node.setdefault("properties", {}).update(merged_props)
                # Add warning to description
            return node
        # ...
    return walk(schema)
```

**CRITICAL ISSUE:** This adapter flattens **ALL** `oneOf` constructs, even nested ones (which OpenAI actually supports).

### OpenaiWrapper Adapter

**File:** `packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/schema_adapters.py:69-97`

**Purpose:** Wrap schema in OpenAI Responses API format envelope

**Order:** 999 (runs last)

**Output Format:**
```python
{
    "format": {
        "type": "json_schema",
        "name": "response",
        "schema": target_  # The adapted schema
    }
}
```

**POTENTIAL ISSUE:** This structure uses `"format"` as the top key, which should be nested under `"text"` parameter in the actual API call. This is handled correctly in the request builder (see below).

---

## 7. Provider Request Build

### OpenAI Request Builder

**File:** `packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/request_builder.py`

**Function:** `build_responses_request()` - lines 81-136

**Signature:**
```python
def build_responses_request(
    *,
    req: Request,
    model: str,
    provider_tools: Sequence[Any] | None = None,
    response_format: Mapping[str, Any] | None = None,
    timeout: float | int | None = None,
) -> dict[str, Any]
```

**Build Logic:**
1. **Resolve response format:**
   - Priority: explicit `response_format` param
   - Fallback 1: `req.provider_response_format` (from codec)
   - Fallback 2: `req.response_schema_json`

2. **Normalize input messages:**
   - Convert OrchestrAI messages to OpenAI format
   - Extract role/content via `model_dump()` or dict access
   - Ensure JSON-serializable

3. **Build metadata:**
   - Include codec identity
   - Include tool declarations
   - Mark response_format type if present
   - Serialize as JSON string (OpenAI expects `metadata.orchestrai` as string)

4. **Construct payload:**
   ```python
   payload = {
       "model": model,
       "input": normalized_messages,
       "previous_response_id": ...,
       "tools": provider_tools,
       "tool_choice": ...,
       "max_output_tokens": ...,
       "timeout": timeout,
       "text": resolved_response_format,  # Schema goes here
   }
   ```

5. **JSON validation:**
   - Run through `json.dumps()` + `json.loads()` to ensure serializability

**CRITICAL:** The `text` parameter receives the entire `provider_response_format` dict, which should have structure:
```python
{
    "format": {
        "type": "json_schema",
        "name": "response",
        "schema": {...}
    }
}
```

This matches the Responses API requirement where `text.format` contains the schema specification.

---

## 8. OpenAI API Call

### Provider Backend

**File:** `packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/openai.py`

**Class:** `OpenAIResponsesProvider`

**Decorator:** `@provider_backend(namespace=PROVIDER_NAME, kind=API_SURFACE, name="backend")`

**Constants:** (from `.constants`)
- `PROVIDER_NAME` = "openai-prod" (inferred)
- `API_SURFACE` = "responses"
- `DEFAULT_MODEL` = likely "gpt-4o-mini" or similar

### API Call Flow

**Method:** `async def call(self, req: Request, timeout: float | None = None) -> Response`
**Lines:** 98-131

**Steps:**
1. **Validate client:**
   - Check API key present
   - Check OpenAI client initialized

2. **Build request payload:**
   ```python
   raw_kwargs = build_responses_request(
       req=req,
       model=model_name,
       provider_tools=native_tools,
       response_format=getattr(req, "provider_response_format", None) or ...,
       timeout=timeout_s,
   )
   ```

3. **Make API call:**
   ```python
   resp = await self._client.responses.create(**clean_kwargs(raw_kwargs))
   ```

4. **Adapt response:**
   ```python
   return self.adapt_response(resp, output_schema_cls=req.response_schema)
   ```

**Client Initialization:**
- **Lines:** 69-87
- Uses `openai.AsyncOpenAI` if package available
- Reads API key from `OPENAI_API_KEY` env var
- Optional `base_url` and `timeout` configuration

---

## 9. Response Reception

### Response Extraction

**Provider Methods:** (lines 137-201)

**`_extract_text()`:**
- Iterates through `resp.output` items
- Skips reasoning items
- Extracts text from message items
- Concatenates text parts
- Fallback to `resp.output_text` or `resp.text`

**`_extract_outputs()`:**
- Collects non-message output items (tool calls, images, etc.)
- Filters out reasoning and message types

**`_extract_usage()`:**
- Extracts token usage stats from `resp.usage`

**`_extract_provider_meta()`:**
- Captures model, id, and raw response dump

**Response Structure (OpenAI):**
```python
{
    "id": "resp_...",
    "model": "gpt-4o-mini",
    "output": [
        {
            "type": "message",
            "content": [
                {"type": "output_text", "text": "..."}
            ]
        }
    ],
    "usage": {...}
}
```

**Structured Output Location:**
- If structured output requested, OpenAI returns it in:
  - `output[].content[].text` as JSON string
  - OR provider-specific `structured` field in metadata
  - Codec's `extract_structured_candidate()` handles extraction

---

## 10. Codec Decoding

### Decoding Flow

**File:** `packages/orchestrai/src/orchestrai/contrib/provider_codecs/openai/responses_json.py:130-182`

**Method:** `async def adecode(self, resp: Response) -> Any | None`

**Steps:**
1. **Extract candidate:**
   ```python
   candidate = self.extract_structured_candidate(resp)
   ```
   - Checks `resp.provider_meta["structured"]` first
   - Fallback to parsing JSON from text output
   - Returns dict or None

2. **Locate schema class:**
   - Priority 1: `resp.request.response_schema`
   - Priority 2: Service's schema (via `_get_schema_from_service()`)
   - Priority 3: Codec's class-level schema

3. **Validate into Pydantic:**
   ```python
   if callable(schema_cls.model_validate):
       return schema_cls.model_validate(candidate)
   else:
       return schema_cls(**candidate)
   ```

4. **Error handling:**
   - Pydantic `ValidationError` → `CodecDecodeError`
   - Generic exceptions → `CodecDecodeError`

**Return value:**
- Pydantic model instance (if schema available)
- Raw dict (if no schema)
- None (if no structured output)

---

## 11. Validation/Parsing

### Pydantic Validation

**Happens in codec decode step** (see above)

**Pydantic Features Used:**
- `model_validate(dict)` - Pydantic v2 validation
- Field validators
- Type coercion
- Discriminated unions (via `Field(discriminator="kind")`)

**Validation Failures:**
- Wrapped in `CodecDecodeError`
- Original Pydantic error attached as `__cause__`

### Structured Output Candidate Extraction

**Base Codec Method:** (inferred from usage)
```python
def extract_structured_candidate(self, resp: Response) -> dict | None:
    # Priority 1: Provider-native structured field
    if "structured" in resp.provider_meta:
        return resp.provider_meta["structured"]

    # Priority 2: Parse JSON from text output
    text = self._extract_text(resp)
    if text:
        try:
            return json.loads(text)
        except JSONDecodeError:
            return None

    return None
```

---

## 12. Persistence

### Persistence Hooks (Inferred)

**Django Integration:**
- Response DTOs include `db_pk`, `object_db_pk`, etc.
- Persistence handled by Django signals/listeners (not in scope here)
- Structured output (validated Pydantic instance) passed to persistence layer

**Persistence Pattern:**
- Parsed schema instances are typed Pydantic objects
- Persistence layer can:
  - Extract fields by name
  - Serialize to JSON for JSONB columns
  - Map to ORM models via field correspondence
  - Handle idempotency via correlation IDs

**Current Limitation:**
- No built-in "section registry" for splitting composite outputs
- Each schema is treated as monolithic unit
- Labs cannot easily define per-section persistence handlers

---

## Summary: Key Files and Functions

### Schema Definition
- `orchestrai/types/base.py` - `StrictBaseModel`
- `orchestrai/components/schemas/base.py` - `BaseOutputSchema`
- `orchestrai_django/components/schemas/types.py` - `DjangoBaseOutputSchema`
- `SimWorks/{app}/orca/schemas/*.py` - Concrete schemas

### Schema Registration
- `orchestrai/decorators/components/schema_decorator.py` - `@schema` decorator

### Schema Resolution
- `orchestrai/resolve/schema.py` - `resolve_schema()`

### Codec Encoding
- `orchestrai/contrib/provider_codecs/openai/responses_json.py:73-128` - `aencode()`

### Schema Adaptation
- `orchestrai/contrib/provider_backends/openai/schema_adapters.py:24-66` - `FlattenUnions`
- `orchestrai/contrib/provider_backends/openai/schema_adapters.py:69-97` - `OpenaiWrapper`

### Request Building
- `orchestrai/contrib/provider_backends/openai/request_builder.py:81-136` - `build_responses_request()`

### API Call
- `orchestrai/contrib/provider_backends/openai/openai.py:98-131` - `OpenAIResponsesProvider.call()`

### Response Extraction
- `orchestrai/contrib/provider_backends/openai/openai.py:137-201` - Extract methods

### Codec Decoding
- `orchestrai/contrib/provider_codecs/openai/responses_json.py:130-182` - `adecode()`

---

## Identified Issues

### 1. Over-Aggressive Union Flattening
**Problem:** `FlattenUnions` flattens ALL `oneOf` constructs, even nested ones
**Impact:** Loss of type safety, unnecessary schema mutations
**Root Cause:** Adapter designed when OpenAI rejected all unions
**Status:** Likely obsolete given current OpenAI support for nested unions

### 2. No Per-Section Schema Composition
**Problem:** Labs cannot define typed sub-sections for structured outputs
**Impact:** Large monolithic schemas, hard to persist individual sections
**Example:** Cannot separately type `PatientDemographics`, `LabResults`, `Messages`
**Need:** Registry pattern for composable schema sections

### 3. Schema Adapter Applied Twice (Potential)
**Problem:** `resolve_schema()` used to apply adapters, now comments say "codec's responsibility"
**Impact:** Possible confusion, legacy code paths
**Status:** Needs verification - ensure adapters only run once

### 4. Unclear Wrapper Format
**Problem:** `OpenaiWrapper` produces `{"format": {...}}` but API needs `{"text": {"format": {...}}}`
**Resolution:** `request_builder.py` correctly nests under `text` parameter
**Status:** Working but confusing - wrapper naming doesn't match final structure

### 5. Discriminated Unions at Field Level
**Finding:** `MetafieldItem` uses discriminated unions successfully
**Status:** This works! Proves nested unions are supported
**Action:** Use this pattern more explicitly, document it

---

## Next Steps (Planning Phase)

1. **Test nested unions with OpenAI API** to confirm support
2. **Redesign `FlattenUnions`** to only handle root-level unions (or remove entirely)
3. **Create schema composition framework** for per-section types
4. **Standardize wrapper format** to match API structure clearly
5. **Add comprehensive tests** for all schema workflow branches
6. **Document schema design patterns** for Lab authors

---

## File Location Quick Reference

| Component | File Path |
|-----------|-----------|
| StrictBaseModel | `packages/orchestrai/src/orchestrai/types/base.py` |
| BaseOutputSchema | `packages/orchestrai/src/orchestrai/components/schemas/base.py` |
| DjangoBaseOutputSchema | `packages/orchestrai_django/src/orchestrai_django/components/schemas/types.py` |
| Example Schemas | `SimWorks/chatlab/orca/schemas/patient.py` |
| Metadata Types | `SimWorks/chatlab/orca/types/metadata.py` |
| Schema Resolver | `packages/orchestrai/src/orchestrai/resolve/schema.py` |
| OpenAI JSON Codec | `packages/orchestrai/src/orchestrai/contrib/provider_codecs/openai/responses_json.py` |
| Schema Adapters | `packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/schema_adapters.py` |
| Request Builder | `packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/request_builder.py` |
| OpenAI Provider | `packages/orchestrai/src/orchestrai/contrib/provider_backends/openai/openai.py` |
| Codec Tests | `tests/orchestrai/components/codecs/openai/test_responses_json_codec.py` |
| Example Service | `SimWorks/chatlab/orca/services/patient.py` |
