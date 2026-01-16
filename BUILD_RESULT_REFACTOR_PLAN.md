# Build/Result Schema Refactor Plan

## Current State Analysis

### Existing Type Hierarchy
```
orchestrai/types/
├── base.py           # StrictBaseModel (extra="forbid")
├── content.py        # Base*Content classes
├── input.py          # InputContent, InputTextContent, etc.
├── output.py         # OutputContent, OutputTextContent, etc.
├── messages.py       # InputItem, OutputItem
├── meta.py           # Metafield
└── transport.py      # Request, Response
```

### Problems with Current Approach

1. **Mixed responsibilities**: Same types used for both construction and schema generation
2. **No defaults for construction**: Recent strict mode fixes removed defaults, breaking ergonomics
3. **Tight coupling**: Can't optimize for construction vs validation separately

## Target Architecture

### Three-Layer Pattern

```python
# Layer 1: Base (shared semantics)
class BaseTextContent(BaseModel):
    """Defines field set and semantics."""
    text: str

# Layer 2: Build (ergonomic construction)
class BuildTextContent(BaseTextContent):
    """For constructing payloads - defaults allowed."""
    type: Literal["text"] = "text"  # Default provided
    text: str = ""  # Optional default

# Layer 3: Result (schema-authoritative)
class ResultTextContent(StrictBaseModel):
    """For schemas, validation, persistence - strict."""
    type: Literal["text"]  # No default - required
    text: str  # No default - required
```

### Schema Families to Refactor

#### 1. Content Types
**Current**: `BaseTextContent`, `OutputTextContent`, `InputTextContent`
**New**:
- Base: `BaseTextContent`, `BaseImageContent`, `BaseAudioContent`, etc.
- Build: `BuildTextContent`, `BuildImageContent`, etc. (for construction)
- Result: `ResultTextContent`, `ResultImageContent`, etc. (for schemas)

#### 2. Message Items
**Current**: `InputItem`, `OutputItem`
**New**:
- Base: `BaseMessageItem`
- Build: `BuildMessageItem`
- Result: `ResultMessageItem`

#### 3. Metadata
**Current**: `Metafield`
**New**:
- Already strict, just rename: `ResultMetafield`
- Add `BuildMetafield` with defaults if needed

#### 4. Tool Types
**Current**: `BaseToolCallContent`, `BaseToolResultContent`
**New**:
- Base: Keep as-is
- Build: `BuildToolCallContent`, `BuildToolResultContent`
- Result: `ResultToolCallContent`, `ResultToolResultContent`

## Implementation Phases

### Phase 1: Create Result* Types (Strict, Schema-Authoritative)

**Files to create/modify**:
- `packages/orchestrai/src/orchestrai/types/result.py` (new file)
- `packages/orchestrai/src/orchestrai/types/result_content.py` (new file)

**Types to create**:
```python
# result_content.py
class ResultTextContent(StrictBaseModel):
    type: Literal["text"]
    text: str

class ResultImageContent(StrictBaseModel):
    type: Literal["image"]
    mime_type: str
    data_b64: str

# result.py
class ResultMessageItem(StrictBaseModel):
    role: ContentRole
    content: list[ResultContent]  # Union of Result* content types
    item_meta: list[ResultMetafield]

class ResultMetafield(StrictBaseModel):
    key: str
    value: str | int | float | bool
```

### Phase 2: Create Build* Types (Ergonomic Construction)

**Files to create/modify**:
- `packages/orchestrai/src/orchestrai/types/build.py` (new file)
- `packages/orchestrai/src/orchestrai/types/build_content.py` (new file)

**Types to create**:
```python
# build_content.py
class BuildTextContent(BaseTextContent):
    type: Literal["text"] = "text"  # Default provided

class BuildImageContent(BaseImageContent):
    type: Literal["image"] = "image"

# build.py
class BuildMessageItem(BaseModel):
    role: ContentRole
    content: list[BuildContent]
    item_meta: list[BuildMetafield] = Field(default_factory=list)  # Default!
```

### Phase 3: Update Schema Definitions

**Files to modify**:
- `SimWorks/chatlab/orca/schemas/patient.py`
- `SimWorks/chatlab/orca/schemas/mixins.py`
- `SimWorks/simulation/orca/schemas/feedback.py`

**Changes**:
```python
# BEFORE (using Output*)
from orchestrai.types import OutputItem

class PatientResponseBaseMixin(StrictBaseModel):
    messages: list[OutputItem] = Field(...)

# AFTER (using Result*)
from orchestrai.types import ResultMessageItem

class PatientResponseBaseMixin(StrictBaseModel):
    messages: list[ResultMessageItem] = Field(...)
```

### Phase 4: Update Construction Sites

**Files to modify**:
- `packages/orchestrai/src/orchestrai/components/providerkit/provider.py`
- All test files
- Any service code that constructs messages

**Changes**:
```python
# BEFORE
OutputItem(
    role=ContentRole.ASSISTANT,
    content=[OutputTextContent(type="output_text", text=text)],
    item_meta=[],
)

# AFTER
BuildMessageItem(
    role=ContentRole.ASSISTANT,
    content=[BuildTextContent(text=text)],  # type auto-filled by default
    # item_meta auto-filled by default_factory
)
```

### Phase 5: Add Conversion Utilities

**File**: `packages/orchestrai/src/orchestrai/types/converters.py` (new)

```python
def build_to_result(build_item: BuildMessageItem) -> ResultMessageItem:
    """Convert Build* to Result* for validation/persistence."""
    return ResultMessageItem.model_validate(build_item.model_dump())

def result_to_build(result_item: ResultMessageItem) -> BuildMessageItem:
    """Convert Result* to Build* for manipulation."""
    return BuildMessageItem.model_validate(result_item.model_dump())
```

### Phase 6: Add Comprehensive Tests

**New test files**:
- `tests/schemas/test_result_schemas.py` - Schema generation tests
- `tests/schemas/test_build_types.py` - Construction ergonomics tests
- `tests/schemas/test_schema_validation.py` - Validation behavior tests
- `tests/schemas/test_schema_strictness.py` - Strict mode compliance tests

**Test coverage**:
1. **Schema generation** - All Result* types generate strict schemas
2. **Validation** - Required fields, literals, unions work correctly
3. **Construction** - Build* types provide ergonomic defaults
4. **Conversion** - Build<->Result conversion is lossless

## Migration Strategy

### Backward Compatibility Approach

1. **Keep old types** temporarily as deprecated aliases
2. **Add new types** alongside
3. **Gradually migrate** usage
4. **Remove old types** after migration complete

### Deprecation Path

```python
# output.py
from .result_content import ResultTextContent

# Deprecated alias
OutputTextContent = ResultTextContent
warnings.warn("OutputTextContent is deprecated, use ResultTextContent", DeprecationWarning)
```

## Success Criteria

- ✅ All structured output schemas use only Result* types
- ✅ All Result* object schemas have `additionalProperties: false`
- ✅ All construction code uses Build* types (ergonomic)
- ✅ Schema generation tests pass
- ✅ Validation tests pass
- ✅ Full test suite passes
- ✅ No Input*/Output* naming in new code

## Files to Create

1. `packages/orchestrai/src/orchestrai/types/result.py`
2. `packages/orchestrai/src/orchestrai/types/result_content.py`
3. `packages/orchestrai/src/orchestrai/types/build.py`
4. `packages/orchestrai/src/orchestrai/types/build_content.py`
5. `packages/orchestrai/src/orchestrai/types/converters.py`
6. `tests/schemas/test_result_schemas.py`
7. `tests/schemas/test_build_types.py`
8. `tests/schemas/test_schema_validation.py`
9. `tests/schemas/test_schema_strictness.py`

## Files to Modify

1. `SimWorks/chatlab/orca/schemas/patient.py`
2. `SimWorks/chatlab/orca/schemas/mixins.py`
3. `SimWorks/simulation/orca/schemas/feedback.py`
4. `packages/orchestrai/src/orchestrai/components/providerkit/provider.py`
5. All test files using Output*/Input* types
6. `packages/orchestrai/src/orchestrai/types/__init__.py` (exports)

## Estimated Impact

- **New files**: 9
- **Modified files**: ~20-30
- **Lines of code**: ~2000-3000 new/modified
- **Test coverage**: +500-800 lines
