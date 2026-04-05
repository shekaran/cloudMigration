"""Base models and shared types used across the canonical data model."""

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DependencyType(str, Enum):
    """Types of relationships between resources."""

    NETWORK = "network"
    STORAGE = "storage"
    COMPUTE = "compute"
    SECURITY = "security"
    RUNTIME = "runtime"


class ResourceDependency(BaseModel):
    """A structured dependency between two resources."""

    source_id: UUID = Field(description="ID of the resource that depends on another")
    target_id: UUID = Field(description="ID of the resource being depended upon")
    dependency_type: DependencyType = Field(description="Category of the dependency")
    description: str = Field(default="", description="Human-readable explanation")


class BaseResource(BaseModel):
    """Base for all canonical resource models."""

    id: UUID = Field(default_factory=uuid4, description="Unique resource identifier")
    name: str = Field(description="Human-readable resource name")
    platform: str = Field(description="Source platform (e.g. ibm_classic, vmware)")
    metadata: dict = Field(default_factory=dict, description="Platform-specific metadata")
    tags: list[str] = Field(default_factory=list, description="User-defined tags")
    dependencies: list[ResourceDependency] = Field(
        default_factory=list, description="Relationships to other resources"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this record was created",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this record was last updated",
    )
