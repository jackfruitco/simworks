"""
This module defines the various JSON output schemas for OpenAI's structured outputs.
"""


def dynamic_type(
    base: str, initial: bool, *, only: bool = False, disabled: bool = False
):
    """
    Return a type definition for JSON Schema based on the base type, the 'initial'
    flag, and whether this field is to be treated as exclusively present when initial.

    - If only is True: returns `base` if initial is True, else "null".
    - Otherwise: returns `base` if initial is True, else [base, "null"].

    - Use:
      - always required: `initial=True, only=False`.
      - always optional: `initial=False, only=False`.
      - initial required: `initial=True, only=False`.
      - initial *only*: `initial=initial, only=True`.
      - disable key: `disabled=True`.

    :return string: JSON Schema Type
    """
    if disabled:
        return "null"
    if only:
        return base if initial else "null"
    else:
        return base if initial else [base, "null"]


async def build_message_output_schema(initial: bool = False) -> dict:
    """Return dict with JSON Schema for OpenAI Response Output."""
    return {
        "format": {
            "type": "json_schema",
            "name": "patient_response",
            "strict": False,
            "schema": {
                "type": dynamic_type(base="object", initial=True, only=False),
                "properties": {
                    "messages": {
                        "type": dynamic_type("array", True, only=False),
                        "description": "Simulated SMS messages from the patient.",
                        "items": {
                            "type": dynamic_type("object", True, only=False),
                            "properties": {
                                "sender": {
                                    "type": dynamic_type("string", True, only=False),
                                    "description": "The role of the sender, e.g., patient.",
                                },
                                "content": {
                                    "type": dynamic_type("string", True, only=False),
                                    "description": "The content of the message sent by the patient.",
                                },
                            },
                            "required": ["sender", "content"],
                            "additionalProperties": False,
                        },
                    },
                    "metadata": {
                        "type": dynamic_type("object", initial, only=False),
                        "description": "Metadata about the patient.",
                        "properties": {
                            "patient_metadata": {
                                "type": dynamic_type(
                                    "object", initial, only=True
                                ),  # initial_only
                                "description": "Patient metadata.",
                                "properties": {
                                    "age": {
                                        "type": dynamic_type(
                                            "number", initial, only=True
                                        ),
                                        "description": "The age of the patient.",
                                    },
                                    "gender": {
                                        "type": dynamic_type(
                                            "string", initial, only=True
                                        ),
                                        "description": "The gender of the patient.",
                                        "enum": ["male", "female"],
                                    },
                                    "location": {
                                        "type": dynamic_type(
                                            "string", initial, only=True
                                        ),
                                        "description": "The location of the patient. Can include all or part of City, State/Province, Country.",
                                    },
                                    "medical_history": {
                                        "type": dynamic_type(
                                            "array", False, only=False
                                        ),  # always_optional: union with null
                                        "description": "Known medical history for the patient. Does not need to be relevant.",
                                        "items": {
                                            "type": dynamic_type(
                                                "object", False, only=False
                                            ),
                                            "properties": {
                                                "diagnosis": {
                                                    "type": dynamic_type(
                                                        "string", False, only=False
                                                    ),
                                                    "description": "The diagnosis or description of problem.",
                                                },
                                                "resolved": {
                                                    "type": dynamic_type(
                                                        "string", False, only=False
                                                    ),
                                                    "description": "The diagnosis or description of problem.",
                                                    "enum": [
                                                        "resolved",
                                                        "ongoing",
                                                        "unsure",
                                                        "unknown",
                                                    ],
                                                },
                                                "duration": {
                                                    "type": dynamic_type(
                                                        "string", False, only=False
                                                    ),
                                                    "description": "The time this problem started, or time since it began.",
                                                },
                                            },
                                            "required": [
                                                "diagnosis",
                                                "resolved",
                                                "duration",
                                            ],
                                            "additionalProperties": False,
                                        },
                                    },
                                    "additional": {
                                        "type": dynamic_type(
                                            "array", False, only=False
                                        ),
                                        "description": "Additional patient metadata as key:value pairs.",
                                        "items": {
                                            "type": dynamic_type(
                                                "object", True, only=False
                                            ),
                                            "properties": {
                                                "key": {
                                                    "type": dynamic_type(
                                                        "string", False, only=False
                                                    ),
                                                    "description": "The key of the patient metadata.",
                                                },
                                                "value": {
                                                    "type": dynamic_type(
                                                        "string", False, only=False
                                                    ),
                                                    "description": "The value of the patient metadata.",
                                                },
                                            },
                                            "required": ["key", "value"],
                                            "additionalProperties": False,
                                        },
                                    },
                                },
                                "required": [
                                    "age",
                                    "gender",
                                    "location",
                                    "medical_history",
                                    "additional",
                                ],
                                "additionalProperties": False,
                            },
                            "simulation_metadata": {
                                "type": dynamic_type(
                                    "array", initial, only=False
                                ),  # initial_required: depends on 'initial'
                                "description": "Simulation metadata.",
                                "items": {
                                    "type": dynamic_type("object", True, only=False),
                                    "properties": {
                                        "chief_complaint": {
                                            "type": dynamic_type(
                                                "string", initial, only=True
                                            ),
                                            "description": "The chief complaint of the patient (chief complaint only, not a sentence).",
                                        },
                                        "additional": {
                                            "type": dynamic_type(
                                                "array", False, only=False
                                            ),
                                            "description": "Additional simulation metadata.",
                                            "items": {
                                                "type": dynamic_type(
                                                    "object", True, only=False
                                                ),
                                                "properties": {
                                                    "key": {
                                                        "type": dynamic_type(
                                                            "string", True, only=False
                                                        ),
                                                        "description": "The key of the simulation metadata.",
                                                    },
                                                    "value": {
                                                        "type": dynamic_type(
                                                            "string", True, only=False
                                                        ),
                                                        "description": "The value of the simulation metadata.",
                                                    },
                                                },
                                                "required": ["key", "value"],
                                                "additionalProperties": False,
                                            },
                                        },
                                    },
                                    "required": ["chief_complaint", "additional"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["patient_metadata", "simulation_metadata"],
                        "additionalProperties": False,
                    },
                },
                "required": ["messages", "metadata"],
                "additionalProperties": False,
            },
        }
    }
