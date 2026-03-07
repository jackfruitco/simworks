# Schemas

## Base Imports

```python
from orchestrai_django.components.schemas import (
    DjangoBaseOutputBlock,
    DjangoBaseOutputItem,
    DjangoBaseOutputSchema,
)
```

## Example

```python
class TextBlock(DjangoBaseOutputBlock):
    type: str = "text"
    text: str


class MessageItem(DjangoBaseOutputItem):
    role: str
    content: list[TextBlock]


class PatientReplySchema(DjangoBaseOutputSchema):
    message: list[MessageItem]
```

Attach schema to service:

```python
@orca.service
class GenerateReply(..., DjangoBaseService):
    response_schema = PatientReplySchema
```

## Resolution

Schemas may be referenced directly on a service or resolved through registry identity.
