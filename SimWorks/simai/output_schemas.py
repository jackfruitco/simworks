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


async def message_schema(initial: bool = False) -> dict:
    """Return dict with JSON Schema for OpenAI Response Output."""
    return {
        "format": {
            "type": "json_schema",
            "name": "patient_response",
            "strict": True,
            "schema": {
                "type": dynamic_type(base="object", initial=True, only=False),
                "required": ["messages", "metadata"],
                "additionalProperties": False,
                "properties": {
                    "messages": {
                        "type": dynamic_type("array", True, only=False),
                        "description": "Simulated SMS messages from the patient.",
                        "items": {
                            "type": dynamic_type("object", True, only=False),
                            "required": ["sender", "content"],
                            "additionalProperties": False,
                            "properties": {
                                "sender": {
                                    "type": dynamic_type("string", True, only=False),
                                    "description": "The role of the sender, e.g., patient.",
                                    "enum": ["patient"]
                                },
                                "content": {
                                    "type": dynamic_type("string", True, only=False),
                                    "description": "The content of the message sent by the patient.",
                                },
                            },
                        },
                    },
                    "metadata": {
                        "type": dynamic_type("object", initial, only=False),
                        "description": "Metadata about the patient.",
                        "required": ["patient_metadata", "simulation_metadata", "scenario_metadata"],
                        "additionalProperties": False,
                        "properties": {
                            "patient_metadata": {
                                "description": "Patient metadata.",
                                "type": dynamic_type("object", initial, only=True),
                                "required": [
                                    "name",
                                    "age",
                                    "gender",
                                    "location",
                                    "medical_history",
                                    "additional",
                                ],
                                "additionalProperties": False,
                                "properties": {
                                    "name": {
                                        "type": dynamic_type(
                                            "string", True, only=True
                                        ),
                                        "description": "The name of the patient.",
                                    },
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
                                        "description": "The gender of the patient. Should match the name.",
                                        "enum": ["male", "female"],
                                    },
                                    "location": {
                                        "type": dynamic_type(
                                            "string", initial, only=True
                                        ),
                                        "description": "The current location of the patient. Can include all or part of City, State/Province, Country.",
                                    },
                                    "medical_history": {
                                        "type": dynamic_type("array", False, only=False),
                                        "description": "Known medical history for the patient. Does not need to be relevant.",
                                        "additionalProperties": False,
                                        "items": {
                                            "type": dynamic_type("object", False, only=False),
                                            "additionalProperties": False,
                                            "required": [
                                                "diagnosis",
                                                "resolved",
                                                "duration",
                                            ],
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
                                        },
                                    },
                                    "additional": {
                                        "description": "Additional patient metadata as key:value pairs.",
                                        "type": dynamic_type("array", False, only=False),
                                        "additionalProperties": False,
                                        "items": {
                                            "type": dynamic_type("object", True, only=False),
                                            "required": ["key", "value"],
                                            "additionalProperties": False,
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
                                        },
                                    },
                                },
                            },
                            # Patient metadata related to the scenario
                            "simulation_metadata": {
                                "type": dynamic_type("array", initial, only=False),
                                "description": "Simulation metadata.",
                                "items": {
                                    "description": "Additional simulation metadata.",
                                    "type": dynamic_type("object", False, only=False),
                                    "required": ["key", "value"],
                                    "additionalProperties": False,
                                    "properties": {
                                        "key": {
                                            "description": "The key of the simulation metadata.",
                                            "type": dynamic_type(
                                                "string", True, only=False
                                            ),
                                        },
                                        "value": {
                                            "description": "The value of the simulation metadata.",
                                            "type": dynamic_type(
                                                "string", True, only=False
                                            ),
                                        },
                                    },
                                },
                            },
                            "scenario_metadata": {
                                "description": "Metadata about the scenario.",
                                "type": dynamic_type("object", initial, only=True),
                                "required": ["diagnosis", "chief_complaint"],
                                "additionalProperties": False,
                                "properties": {
                                    "diagnosis": {
                                        "description": "The diagnosis for the scenario script.",
                                        "type": "string",
                                    },
                                    "chief_complaint": {
                                        "description": "The chief complaint for the scenario script.",
                                        "type": "string",
                                    }
                                }
                            }
                        },
                    },
                },
            },
        }
    }

async def feedback_schema() -> dict:
    """Return dict with JSON Schema for OpenAI Feedback Output."""
    return {
        "format": {
            "type": "json_schema",
            "name": "user_feedback",
            "strict": True,
            "schema": {
                "type": "object",
                "required": ["correct_diagnosis", "correct_treatment_plan", "patient_experience", "feedback", "topics"],
                "additionalProperties": False,
                "properties": {
                    "correct_diagnosis": {
                        "type": "string",
                        "description": "Whether the diagnosis provided or discussed with the patient is correct or not.",
                        "enum": ["true", "false", "partial"],
                    },
                    "correct_treatment_plan": {
                        "type": "string",
                        "description": "The treatment plan to which the patient is correct or not.",
                        "enum": ["true", "false", "partial"],
                    },
                    "patient_experience": {
                        "type": "number",
                        "description": "The patient experience that the patient received, including clarity of instructions, hospitality, etc.",
                        "enum": [0, 1, 2, 3, 4, 5],
                    },
                    "feedback": {
                        "type": "string",
                        "description": "Specific feedback to user based on the simulation.",
                        # "minLength": 700,
                        # "maxLength": 2000,
                    },
                    "topics": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": "The topics that the user should study or research to further development and understanding.",
                        }
                    }
                }
            }
        }
    }