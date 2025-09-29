# simcore/ai/schemas/normalized_types.py
import logging
import warnings
from importlib import import_module
from typing import Optional, List, Dict, Any, Literal, Annotated, Union, TypeVar

from pydantic import Field

from simcore.ai.schemas import StrictBaseModel, StrictOutputSchema

warnings.warn("This module is deprecated. Use simcore.ai.schemas.types instead.", DeprecationWarning)

logger = logging.getLogger(__name__)

# ---------- Union Type for Output Schemas --------------------------------------------
OutputSchemaType = TypeVar("OutputSchemaType", bound=StrictOutputSchema)


# ---------- Normalized AI types ------------------------------------------------------
class NormalizedAttachment(StrictBaseModel):
    type: Literal["image"]

    b64: Optional[str] = None
    file: Optional[Any] = None
    url: Optional[str] = None

    format: Optional[str] = None  # "png", "jpeg", etc.
    size: Optional[str] = None  # "1024x1024"
    background: Optional[str] = None

    provider_meta: Dict[str, Any] = Field(default_factory=dict)

    # linkage after persistence (post-persist)
    db_pk: Optional[int] = None
    db_model: Optional[str] = None
    slug: Optional[str] = None

    async def persist_response(self, simulation: Any):
        """
        Convenience helper: persist this attachment for the given Simulation.

        Delegates to simcore.ai.persist.persist_attachment to avoid ORM coupling.
        """
        from ..utils import persist_attachment
        return await persist_attachment(simulation, self)

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.Attachment instead.", DeprecationWarning)
        super().__init__(**data)


class NormalizedAIMessage(StrictBaseModel):
    role: str
    content: str

    db_pk: Optional[int] = None  # django object pk
    tool_calls: Optional[List[Dict[str, Any]]] = None

    attachments: List[NormalizedAttachment] = Field(default_factory=list)

    async def persist(self, simulation: Any, **kwargs: Any):
        """
        Convenience helper: persist this message for the given Simulation.

        Delegates to simcore.ai.persist.persist_message to avoid ORM coupling.
        """
        from ..utils import persist_message
        return await persist_message(simulation, self, **kwargs)

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.Message instead.", DeprecationWarning)
        super().__init__(**data)


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

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.Metafield instead.", DeprecationWarning)
        super().__init__(**data)


class GenericMeta(MetaBase):
    type: Literal["generic"]
    value: Optional[str] = None
    extra: Dict[str, Any] = {}

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.GenericMetafield instead.",
                      DeprecationWarning)
        super().__init__(**data)


class LabResultMeta(MetaBase):
    # Deprecated, use simcore.ai.schemas.types.LabResultMetafield instead
    type: Literal["lab_result"]
    panel_name: Optional[str] = None
    result_name: str
    result_value: str
    result_unit: str
    reference_range_low: str
    reference_range_high: str
    result_flag: str
    result_comment: str

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.LabResultMetafield instead.",
                      DeprecationWarning)
        super().__init__(**data)


class RadResultMeta(MetaBase):
    # Deprecated, use simcore.ai.schemas.types.RadResultMetafield instead
    type: Literal["rad_result"]
    value: str
    flag: str

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.RadResultMetafield instead.",
                      DeprecationWarning)
        super().__init__(**data)


class PatientHistoryMeta(MetaBase):
    # Deprecated, use simcore.ai.schemas.types.PatientHistoryMetafield instead
    type: Literal["patient_history"]
    value: str
    is_resolved: bool
    duration: str

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.PatientHistoryMetafield instead.",
                      DeprecationWarning)
        super().__init__(**data)


class SimulationFeedbackMeta(MetaBase):
    # Deprecated, use simcore.ai.schemas.types.SimulationFeedbackMetafield instead
    type: Literal["simulation_feedback"]
    value: str

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.SimulationFeedbackMetafield instead.",
                      DeprecationWarning)
        super().__init__(**data)


# ---------- Additional Metadata Types -----------------------------------------------
class PatientDemographicsMeta(MetaBase):
    # Deprecated, use simcore.ai.schemas.types.PatientDemographicsMetafield instead
    type: Literal["patient_demographics"]
    value: str

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.PatientDemographicsMetafield instead.",
                      DeprecationWarning)
        super().__init__(**data)


class SimulationMetaKV(MetaBase):
    # Deprecated, use simcore.ai.schemas.types.SimulationMetadataMetafield instead
    type: Literal["simulation_metadata"]
    value: str

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.SimulationMetafield instead.",
                      DeprecationWarning)
        super().__init__(**data)


class ScenarioMeta(MetaBase):
    # Deprecated, use simcore.ai.schemas.types.ScenarioMetafield instead
    type: Literal["scenario"]
    value: str

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.ScenarioMetafield instead.",
                      DeprecationWarning)
        super().__init__(**data)


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


# ---------- Normalized AI Tools ---------------------------------------------------------------------------------------
class NormalizedAITool(StrictBaseModel):
    # Deprecated, use simcore.ai.schemas.types.AITool instead
    type: str  # e.g. "image_generation"
    function: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.LLMTool instead.", DeprecationWarning)
        super().__init__(**data)


# --------- Normalized AI Request --------------------------------------------------------------------------------------
class NormalizedAIRequest(StrictBaseModel):
    # Deprecated, use simcore.ai.schemas.types.LLMRequest instead
    model: Optional[str] = None
    messages: List[NormalizedAIMessage]
    schema_cls: Any = None
    tools: Optional[List[NormalizedAITool]] = None
    tool_choice: Optional[str] = None
    temperature: Optional[float] = 0.2
    max_output_tokens: Optional[int] = None
    stream: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

    previous_response_id: Optional[str] = None
    image_format: Optional[str] = None

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.LLMRequest instead.", DeprecationWarning)
        super().__init__(**data)


# ---------- Normalized AI Response ------------------------------------------------------------------------------------
class NormalizedAIResponse(StrictBaseModel):
    # Deprecated, use simcore.ai.schemas.types.LLMResponse instead
    messages: List[NormalizedAIMessage]
    metadata: List[NormalizedAIMetadata]
    usage: Dict[str, int] = Field(default_factory=dict)

    image_requested: Optional[bool] = None

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

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.LLMResponse instead.", DeprecationWarning)
        super().__init__(**data)


# ---------- Normalized Stream Chunk -----------------------------------------------------------------------------------
class NormalizedStreamChunk(StrictBaseModel):
    # Deprecated, use simcore.ai.schemas.types.StreamChunk instead
    delta: str = ""
    tool_call_delta: Optional[Dict[str, Any]] = None
    usage_partial: Optional[Dict[str, int]] = None

    def __init__(self, **data):
        warnings.warn("This class is deprecated. Use simcore.ai.schemas.types.StreamChunk instead.", DeprecationWarning)
        super().__init__(**data)
