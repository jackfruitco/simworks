# simcore/ai/schemas/normalized_types.py
import logging
from importlib import import_module
from typing import Optional, List, Dict, Any, Literal, Annotated, Union, TypeVar

from pydantic import BaseModel, Field

from simcore.ai.schemas import StrictBaseModel, StrictOutputSchema

logger = logging.getLogger(__name__)

# ---------- Union Type for Output Schemas --------------------------------------------
OutputSchemaType = TypeVar("OutputSchemaType", bound=StrictOutputSchema)


# ---------- Normalized AI types ------------------------------------------------------
class NormalizedAIMessage(BaseModel):
    role: str
    content: str

    db_pk: Optional[int] = None  # django object pk
    tool_calls: Optional[List[Dict[str, Any]]] = None

    async def persist(self, simulation: Any, **kwargs: Any):
        """
        Convenience helper: persist this message for the given Simulation.

        Delegates to simcore.ai.persist.persist_message to avoid ORM coupling.
        """
        from ..utils import persist_message
        return await persist_message(simulation, self, **kwargs)


class MetaBase(StrictBaseModel):
    type: str
    key: str

    db_pk: Optional[int] = None  # django object pk

    async def persist(self, simulation: Any):
        """
        Convenience helper: persist this metadata item for the given Simulation.

        Delegates to simcore.ai.persist.persist_metadata to avoid ORM coupling.
        """
        from ..utils import persist_metadata
        return await persist_metadata(simulation, self)


class GenericMeta(MetaBase):
    type: Literal["generic"]
    value: Optional[str] = None
    extra: Dict[str, Any] = {}


class LabResultMeta(MetaBase):
    type: Literal["lab_result"]
    value: str
    unit: str
    ref_low: str
    ref_high: str
    flag: str
    panel_name: Optional[str] = None


class RadResultMeta(MetaBase):
    type: Literal["rad_result"]
    value: str
    flag: str


class PatientHistoryMeta(MetaBase):
    type: Literal["patient_history"]
    value: str
    is_resolved: bool
    duration: str


class SimulationFeedbackMeta(MetaBase):
    type: Literal["simulation_feedback"]
    value: str


# ---------- Additional Metadata Types -----------------------------------------------
class PatientDemographicsMeta(MetaBase):
    type: Literal["patient_demographics"]
    value: str


class SimulationMetaKV(MetaBase):
    type: Literal["simulation_metadata"]
    value: str


class ScenarioMeta(MetaBase):
    type: Literal["scenario"]
    value: str


NormalizedAIMetadata = Annotated[
    Union[
        GenericMeta,
        LabResultMeta,
        RadResultMeta,
        PatientHistoryMeta,
        SimulationFeedbackMeta,
        PatientDemographicsMeta,
        SimulationMetaKV,
        ScenarioMeta,
    ],
    Field(discriminator="type"),
]


class NormalizedAIRequest(BaseModel):
    model: Optional[str] = None
    messages: List[NormalizedAIMessage]
    schema_cls: Any = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[str] = None
    temperature: Optional[float] = 0.2
    max_output_tokens: Optional[int] = None
    stream: bool = False
    metadata: Dict[str, Any] = {}

    previous_response_id: Optional[str] = None


class NormalizedAIResponse(BaseModel):
    messages: List[NormalizedAIMessage]
    metadata: List[NormalizedAIMetadata]
    usage: Dict[str, int] = Field(default_factory=dict)

    provider_meta: Dict[str, Any] = Field(default_factory=dict)
    db_pk: Optional[int] = None  # django object pk

    @classmethod
    def normalize(cls, resp: Any, _from: str, *, schema_cls=None) -> "NormalizedAIResponse":
        logger.debug(f"{cls.__name__} received request to normalize response from {_from}. Forwarding...")
        mod = import_module(f"simcore.ai.providers.{_from}")
        data = mod.normalize_response(resp, schema_cls=schema_cls)
        return data if isinstance(data, cls) else cls(**data)

    async def persist_response(self, simulation: Any):
        """
        Convenience helper: persist this response for the given Simulation.

        Delegates to simcore.ai.persist.persist_response to avoid ORM coupling.
        """
        from ..utils import persist_response
        return await persist_response(simulation, self)

    async def persist_full_response(self, simulation: Any):
        """
        Convenience helper: persist the full response, messages, and metadata
        for the given Simulation.

        Delegates to simcore.ai.persist.persist_message to avoid ORM coupling.
        """
        from ..utils import persist_all
        return await persist_all(self, simulation)


class NormalizedStreamChunk(BaseModel):
    delta: str = ""
    tool_call_delta: Optional[Dict[str, Any]] = None
    usage_partial: Optional[Dict[str, int]] = None
