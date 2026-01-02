# OpenAI Schema Notes - Current API Constraints (2026)

## Sources
- [Structured model outputs | OpenAI API](https://platform.openai.com/docs/guides/structured-outputs)
- [Introducing Structured Outputs in the API | OpenAI](https://openai.com/index/introducing-structured-outputs-in-the-api/)
- [Migrate to the Responses API | OpenAI API](https://platform.openai.com/docs/guides/migrate-to-responses)
- [Responses API documentation](https://platform.openai.com/docs/api-reference/responses)
- [Supported schemas](https://platform.openai.com/docs/guides/structured-outputs/supported-schemas)
- [Community discussions](https://community.openai.com/t/responses-api-documentation-on-structured-outputs-is-lacking/1356632)

## API Migration Context

**Current state (2026):**
- **Responses API** is the recommended approach for text generation applications
- **Chat Completions API** is still supported but older
- **Assistants API** is being deprecated (sunset date: August 26, 2026)
- OpenAI is bringing all Assistants features to the Responses API for feature parity

## Structured Outputs in the Responses API

### Key Difference from Chat Completions
In the **Responses API**, structured outputs are specified via **`text.format`** instead of `response_format`.

**Migration pattern:**
```python
# OLD (Chat Completions API)
response = client.chat.completions.create(
    model="gpt-4",
    messages=[...],
    response_format={"type": "json_schema", "json_schema": {...}}
)

# NEW (Responses API)
response = client.responses.create(
    model="gpt-5.2",
    input=[...],
    text={"format": {"type": "json_schema", "schema": {...}}}
)
```

### Exact Request Shape for Responses API

**Standard format structure:**
```python
{
    "model": "gpt-5.2",
    "input": [...],  # List of message dicts with role/content
    "text": {
        "format": {
            "type": "json_schema",
            "schema": {
                # Your JSON Schema here
            }
        }
    }
}
```

**NOTE:** Community reports suggest some confusion in documentation. The correct nesting is:
- `text.format.type` = "json_schema"
- `text.format.schema` = your actual JSON Schema dict

Some implementations may also accept a wrapper with `"name"`:
```python
{
    "type": "json_schema",
    "json_schema": {
        "name": "response",
        "schema": {...}
    }
}
```

## Supported JSON Schema Features

### ✅ SUPPORTED

1. **Root level object**
   - **REQUIRED:** Root schema MUST have `"type": "object"`
   - Must include `"properties"` dict
   - Should include `"required"` array for strict mode

2. **Nested properties**
   - All standard JSON Schema types: string, number, integer, boolean, array, object
   - Nested objects
   - Arrays of primitives and objects

3. **`anyOf` / `oneOf` in NESTED properties**
   - **IMPORTANT:** Unions ARE supported **within nested properties**
   - Example valid schema:
     ```json
     {
       "type": "object",
       "properties": {
         "value": {
           "anyOf": [
             {"type": "string"},
             {"type": "number"}
           ]
         }
       }
     }
     ```

4. **Discriminated unions (nested)**
   - Can use discriminator field pattern in nested properties
   - Example: database item types, linked list structures

5. **Strict mode constraints**
   - `"additionalProperties": false` (or explicit schema)
   - All properties must be explicitly defined
   - Required fields must be in `"required"` array

### ❌ NOT SUPPORTED

1. **Root-level unions**
   - **`anyOf` / `oneOf` at root level NOT supported**
   - Schema like `{"anyOf": [...]}` will FAIL
   - Must wrap in object: `{"type": "object", "properties": {"item": {"anyOf": [...]}}}`

2. **Pydantic Union[A, B] at root**
   - Pydantic models with root-level unions translate to `anyOf` at root
   - Pattern: `Union[TypeA, TypeB]` as root model → NOT supported
   - Workaround: wrap in container object

3. **Missing required fields**
   - In strict mode, all object fields must be in schema
   - `additionalProperties` must be handled correctly

## Strict Mode Requirements

When using `strict: true` (via SDK or schema directives):

1. Root must be `{"type": "object"}`
2. All properties must be explicitly defined
3. `required` array must list all mandatory fields
4. `additionalProperties` should be `false` or an explicit schema
5. No `anyOf`/`oneOf` at root level

## Pydantic Integration

### Current SDK Support (Python)

**Chat Completions API:**
```python
from pydantic import BaseModel
from openai import OpenAI

class CalendarEvent(BaseModel):
    name: str
    date: str
    participants: list[str]

client = OpenAI()
completion = client.beta.chat.completions.parse(
    model="gpt-4",
    messages=[...],
    response_format=CalendarEvent  # SDK handles schema conversion
)
```

**Responses API:**
- The `responses.create` endpoint does NOT have a `.parse()` helper yet
- Must manually convert Pydantic → JSON Schema
- Use `model.model_json_schema()` to generate schema
- Apply any required transformations (e.g., flatten unions if at root)

### Schema Generation Pattern

```python
from pydantic import BaseModel

class MySchema(BaseModel):
    field: str

# Generate JSON Schema
schema_json = MySchema.model_json_schema()

# Result is a dict like:
# {
#   "type": "object",
#   "properties": {"field": {"type": "string"}},
#   "required": ["field"],
#   ...
# }
```

## Common Failure Patterns

### ❌ FAILS: Root-level union from Pydantic
```python
from typing import Union
from pydantic import BaseModel

class TypeA(BaseModel):
    a: str

class TypeB(BaseModel):
    b: int

# This generates anyOf at root → FAILS
RootUnion = Union[TypeA, TypeB]
```

**Error:** `Invalid schema: anyOf not supported at root level`

### ✅ SUCCEEDS: Wrapped union
```python
class Container(BaseModel):
    item: Union[TypeA, TypeB]  # anyOf in nested property → OK
```

### ❌ FAILS: Missing root type
```python
{
    "properties": {"foo": {"type": "string"}}
    # Missing "type": "object" at root
}
```

### ✅ SUCCEEDS: Explicit root object
```python
{
    "type": "object",
    "properties": {"foo": {"type": "string"}},
    "required": ["foo"]
}
```

## Current SimWorks Implementation Gap Analysis

### What We're Doing Now
1. Using `FlattenUnions` adapter to flatten ALL `oneOf` constructs
2. Wrapping schema in OpenAI format envelope
3. Attaching via `text` parameter to Responses API
4. Using `StrictBaseModel` (Pydantic with `extra="forbid"`)

### Potential Issues
1. **Over-aggressive flattening:** We flatten ALL unions, even nested ones (which ARE supported)
2. **Loss of type safety:** Flattened unions lose discriminator enforcement
3. **Unclear necessity:** Need to verify if OpenAI still rejects nested unions (likely NOT)

### What Needs Verification
1. Test nested `anyOf` with current OpenAI API (likely works)
2. Confirm root-level `anyOf` still fails (likely still fails)
3. Determine if we can eliminate `FlattenUnions` entirely by restructuring root schemas

## Recommendations for SimWorks Schema Pipeline

### Minimal Adapter Strategy
1. **Only flatten root-level unions** (if they exist)
2. **Preserve nested unions** (they work fine)
3. **Validate schema structure:**
   - Root has `"type": "object"`
   - Required fields properly declared
   - `additionalProperties` handled correctly

### Target Schema Builder Behavior
```python
def build_openai_json_schema(model: type[BaseModel], *, strict: bool = True) -> dict:
    """
    Build OpenAI-compatible JSON Schema from Pydantic model.

    Rules:
    1. Generate base schema via model.model_json_schema()
    2. Ensure root is {"type": "object"}
    3. If root has anyOf/oneOf → ERROR (must redesign model)
    4. Nested anyOf/oneOf → PRESERVE (supported)
    5. Add strict mode constraints if strict=True
    """
    schema = model.model_json_schema()

    # Validate root structure
    if schema.get("type") != "object":
        raise SchemaError("Root schema must be type 'object'")

    if "anyOf" in schema or "oneOf" in schema:
        raise SchemaError(
            "Root-level unions not supported by OpenAI. "
            "Redesign model with discriminated union in nested property."
        )

    # Nested unions are fine - no flattening needed

    if strict:
        # Ensure strict mode compliance
        _ensure_strict_compliance(schema)

    return schema
```

### Target Format Builder
```python
def build_responses_format(schema: dict, *, name: str = "response") -> dict:
    """Wrap schema in Responses API format."""
    return {
        "format": {
            "type": "json_schema",
            "name": name,
            "schema": schema
        }
    }
```

## Testing Plan for Union Support

### Test Case 1: Nested Union (should work)
```python
class NestedUnionTest(BaseModel):
    value: Union[str, int]  # anyOf in nested property

# Expected: schema accepted, model output validates
```

### Test Case 2: Root Union (should fail)
```python
RootUnionTest = Union[TypeA, TypeB]  # anyOf at root

# Expected: schema rejection by OpenAI API
```

### Test Case 3: Discriminated Nested Union (should work)
```python
from typing import Literal, Annotated
from pydantic import Field

class TypeA(BaseModel):
    kind: Literal["a"]
    value: str

class TypeB(BaseModel):
    kind: Literal["b"]
    value: int

class Container(BaseModel):
    item: Annotated[Union[TypeA, TypeB], Field(discriminator="kind")]

# Expected: schema accepted with discriminator
```

## Conclusion

**Key takeaway:** OpenAI's current Responses API:
- ✅ Supports `anyOf`/`oneOf` in **nested** properties
- ❌ Rejects `anyOf`/`oneOf` at **root** level
- ✅ Requires root `{"type": "object"}`

**SimWorks next steps:**
1. Test nested unions with real API (confirm they work)
2. Eliminate or drastically simplify `FlattenUnions`
3. Redesign any root-level union schemas to use container pattern
4. Document schema design patterns for Lab authors
