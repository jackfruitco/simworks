# orchestrai/apps/conf/models.py

from pydantic import BaseModel, ConfigDict, Field

from orchestrai.client.conf_models import OrcaClientsSettings
from orchestrai.components.providerkit.conf_models import ProvidersSettings


class OrcaDiscoverySettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    apps: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=lambda: ["orchestrai", "ai"])
    extra_modules: list[str] = Field(default_factory=list)
    extra_component_dirs: list[str] = Field(default_factory=list)


class OrcaSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Core
    NAME: str | None = None
    MODE: str = "single_orca"

    # Common default used by client.factory.get_client()
    DEFAULT_CLIENT: str = "default"

    # Discovery
    DISCOVERY: OrcaDiscoverySettings = Field(default_factory=OrcaDiscoverySettings)

    # Typed config
    PROVIDERS: ProvidersSettings = Field(default_factory=ProvidersSettings)
    CLIENTS: OrcaClientsSettings = Field(default_factory=OrcaClientsSettings)