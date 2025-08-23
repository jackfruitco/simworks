import logging

from typing import Type

from openai.types.responses import Response as OpenAIResponse
from openai.types.responses.response_text_config_param import ResponseTextConfigParam
from pydantic import BaseModel, ValidationError

from simai.models import ResponseType
from simai.response_schema import PatientInitialSchema, PatientResultsSchema, SimulationFeedbackSchema
from simai.response_schema import PatientReplySchema

logger = logging.getLogger(__name__)

MODEL_MAP: dict[ResponseType, type[PatientReplySchema | PatientInitialSchema]] = {
    ResponseType.INITIAL: PatientInitialSchema,
    ResponseType.REPLY:  PatientReplySchema,
    ResponseType.PATIENT_RESULTS: PatientResultsSchema,
    ResponseType.FEEDBACK: SimulationFeedbackSchema,
}


def build_response_text_param(model: Type[BaseModel]) -> ResponseTextConfigParam:
    """
    Build the `text` param for openai.responses.create() that
    tells the API to emit JSON matching `model`’s schema.

    :param model: The Pydantic model class to generate a schema for.
    :type model: Type[BaseModel]

    :return: The `text` param for openai.responses.create().
    :rtype: ResponseTextConfigParam
    """
    return {
        "format": {
            "type": "json_schema",
            "name": model.__name__,
            "schema": model.model_json_schema(),
        }
    }


def maybe_coerce_to_schema(
    response: OpenAIResponse,
    response_type: ResponseType
) -> PatientInitialSchema | PatientReplySchema | SimulationFeedbackSchema | str:
    """
    Convert `response.output_text` into a Pydantic model for INITIAL/REPLY types.

    Args:
        response: The OpenAIResponse object.
        response_type: One of ResponseType.INITIAL or REPLY to pick parsing.

    Returns:
        A PatientInitialSchema or PatientReplySchema instance if parsed;
        otherwise the raw `output_text` string.
    """
    ModelClass = MODEL_MAP.get(response_type)
    if not ModelClass:
        logger.debug(f"No pydantic schema found for {response_type.label} output, "
                     f"using combined `output_text` instead")
        return response.output_text

    try:
        logger.debug(f"Validating {response_type.label} output against schema `{ModelClass.__name__}`")
        return ModelClass.model_validate_json(response.output_text)
    except ValidationError as e:
        logger.error("Schema validation failed for %s: %s", response_type.label, e)
        return response.output_text