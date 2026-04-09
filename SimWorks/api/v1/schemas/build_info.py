"""Schemas for build metadata exposed to app clients."""

from pydantic import BaseModel, Field


class BackendBuildInfoOut(BaseModel):
    """Backend runtime metadata for startup display."""

    version: str | None = Field(default=None, description="Installed backend package version")
    commit: str | None = Field(default=None, description="Injected backend source commit SHA")
    build_time: str | None = Field(
        default=None,
        description="Backend artifact build timestamp in UTC when supplied by the build pipeline",
    )


class OrchestraiBuildInfoOut(BaseModel):
    """OrchestrAI package metadata for startup display."""

    version: str | None = Field(default=None, description="Installed OrchestrAI package version")


class BuildInfoOut(BaseModel):
    """Best-effort build metadata for the mobile splash screen."""

    backend: BackendBuildInfoOut
    orchestrai: OrchestraiBuildInfoOut
