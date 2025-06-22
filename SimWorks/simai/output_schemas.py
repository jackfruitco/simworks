# simai/output_schemas.py
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
                "required": ["image_requested", "messages", "metadata"],
                "additionalProperties": False,
                "properties": {
                    "image_requested": {
                        "type": dynamic_type("boolean", initial, only=False),
                        "description": "Whether an image was requested by the patient. If true, the patient should provide an image.",
                    },
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
                                "description": "Patient metadata",
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
                                                "is_resolved",
                                                "duration",
                                            ],
                                            "properties": {
                                                "diagnosis": {
                                                    "type": dynamic_type(
                                                        "string", False, only=False
                                                    ),
                                                    "description": "The diagnosis or description of problem.",
                                                },
                                                "is_resolved": {
                                                    "type": dynamic_type(
                                                        "boolean", False, only=False
                                                    ),
                                                    "description": "If the condition is resolved or unresolved/ongoing.",
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
                                        "description": "The medical diagnosis (not the symptom) for the scenario script.",
                                        "type": "string",
                                    },
                                    "chief_complaint": {
                                        "description": "The patient's initial or chief complaint for the scenario script.",
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

async def patient_results_schema(initial: bool = False) -> dict:
    """Return dict with JSON Schema for OpenAI Response Output."""
    return {
        "format": {
            "type": "json_schema",
            "name": "patient_results",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["lab_results", "radiology_results"],
                "properties": {
                    "lab_results": {
                        "type": ["array", "null"],
                        "description": "The lab results of the patient. Each item is a lab result object.",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "order_name",
                                "panel_name",
                                "result_value",
                                "result_unit",
                                "reference_range_low",
                                "reference_range_high",
                                "result_flag",
                                "result_comment"
                            ],
                            "properties": {
                                "order_name": {
                                    "type": "string",
                                    "description": "The name of the order using standardized terminology.",
                                },
                                "panel_name": {
                                    "type": ["string", "null"],
                                    "description": "The name of the lab panel the test is included in.",
                                },
                                "result_value": {
                                    "type": "number",
                                    "description": "The result value of the test, without the unit.",
                                },
                                "result_unit": {
                                    "type": "string",
                                    "description": "The unit of the result value.",
                                },
                                "reference_range_low": {
                                    "type": "number",
                                    "description": "The lower limit of the reference range, without the unit.",
                                },
                                "reference_range_high": {
                                    "type": "number",
                                    "description": "the upper limit of the reference range, without the unit.",
                                },
                                "result_flag": {
                                    "type": "string",
                                    "description": "The result flag.",
                                    "enum": ["HIGH", "LOW", "POS", "NEG", "UNK", "NORMAL", "ABNORMAL", "CRITICAL" ]
                                },
                                "result_comment": {
                                    "type": ["string", "null"],
                                    "description": "The result comment, if applicable, or null.",
                                },
                            },
                        },
                    },
                    "radiology_results": {
                        "type": ["array", "null"],
                        "description": "The radiology results of the patient. Each item is a radiology result object.",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "order_name",
                                "result_value",
                                "result_flag",
                            ],
                            "properties": {
                                "order_name": {
                                    "type": "string",
                                    "description": "The name of the order using standardized terminology.",
                                },
                                "result_value": {
                                    "type": "string",
                                    "description": "The result of the order.",
                                },
                                "result_flag": {
                                    "type": "string",
                                    "description": "The result flag.",
                                    "enum": ["UNK", "NORMAL", "ABNORMAL", "CRITICAL"]
                                },
                            }
                        }
                    }
                }
            }
        }
    }