"""Pydantic response models for API endpoints."""

from typing import Any

from pydantic import BaseModel, Field

from app.models.canonical import (
    ComputeResource,
    NetworkSegment,
    SecurityPolicy,
    StorageVolume,
)


class DiscoveredResources(BaseModel):
    """Normalized canonical resources returned by discovery."""

    compute: list[ComputeResource] = Field(default_factory=list)
    networks: list[NetworkSegment] = Field(default_factory=list)
    security_policies: list[SecurityPolicy] = Field(default_factory=list)
    storage: list[StorageVolume] = Field(default_factory=list)

    @property
    def resource_count(self) -> int:
        """Total number of discovered resources across all categories."""
        return (
            len(self.compute)
            + len(self.networks)
            + len(self.security_policies)
            + len(self.storage)
        )


class DiscoveryResponse(BaseModel):
    """Response from POST /discover/{adapter}."""

    adapter: str = Field(description="Name of the adapter that performed discovery")
    raw_data: dict[str, Any] = Field(description="Raw platform-specific data")
    normalized: DiscoveredResources = Field(description="Canonical model resources")
    resource_count: int = Field(description="Total number of discovered resources")


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(description="Error type")
    detail: str = Field(description="Human-readable error message")
