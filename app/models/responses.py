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


class TranslationResponse(BaseModel):
    """Response from POST /plan/{adapter}."""

    adapter: str = Field(description="Adapter that produced the canonical data")
    vpc_name: str = Field(description="Target VPC name")
    subnets: int = Field(description="Number of subnets planned")
    instances: int = Field(description="Number of instances planned")
    security_groups: int = Field(description="Number of security groups planned")
    terraform_path: str = Field(description="Path to generated Terraform file")


class JobResponse(BaseModel):
    """Response from POST /execute and GET /status/{job_id}."""

    job_id: str = Field(description="Unique job identifier")
    adapter: str = Field(description="Adapter name")
    status: str = Field(description="Current job status")
    started_at: str = Field(description="ISO timestamp when job started")
    completed_at: str | None = Field(default=None, description="ISO timestamp when job finished")
    error: str | None = Field(default=None, description="Error message if failed")
    resource_count: int = Field(default=0, description="Total resources discovered")
    terraform_output: str | None = Field(default=None)
    migration_output_dir: str | None = Field(default=None)
    steps_completed: list[str] = Field(default_factory=list)
    validation_errors: int = Field(default=0, description="Number of validation errors")
    validation_warnings: int = Field(default=0, description="Number of validation warnings")
    strategy_summary: dict[str, int] = Field(
        default_factory=dict, description="Strategy → resource count"
    )
    firewall_conflicts: int = Field(default=0, description="Number of firewall rule conflicts")
    firewall_rules_consolidated: int = Field(default=0, description="Firewall rules after consolidation")
    tier_summary: dict[str, int] = Field(
        default_factory=dict, description="Tier → subnet count"
    )


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(description="Error type")
    detail: str = Field(description="Human-readable error message")
