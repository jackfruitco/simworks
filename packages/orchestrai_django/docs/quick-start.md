# Quick Start

## 1) Define a schema

```python
from orchestrai_django.components.schemas import DjangoBaseOutputItem, DjangoBaseOutputSchema


class MessageItem(DjangoBaseOutputItem):
    role: str


class PatientReplySchema(DjangoBaseOutputSchema):
    message: list[MessageItem]
```

## 2) Define instructions

```python
from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca


@orca.instruction(order=0)
class PatientNameInstruction(BaseInstruction):
    def render_instruction(self) -> str:
        name = self.context.get("patient_name", "the patient")
        return f"You are {name}."


@orca.instruction(order=20)
class StyleInstruction(BaseInstruction):
    instruction = "Respond in concise SMS style."
```

## 3) Define service

```python
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca


@orca.service
class GenerateReply(PatientNameInstruction, StyleInstruction, DjangoBaseService):
    response_schema = PatientReplySchema
    required_context_keys = ("simulation_id",)
```

## 4) Run

```python
service = GenerateReply(context={"simulation_id": 1, "patient_name": "Alex"})
result = await service.arun(user_message="How are you feeling?")
```
