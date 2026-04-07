"""Replication and checkpoint data models — tracks replication lifecycle and execution recovery.

Entities:
- ReplicationState: Per-resource replication tracking with checksum verification
- ExecutionCheckpoint: Workflow-level checkpoint for resume & recovery
"""

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ReplicationStatus(str, Enum):
    """Lifecycle status of a resource replication."""

    PENDING = "pending"
    INITIALIZING = "initializing"
    SYNCING = "syncing"
    DELTA_SYNCING = "delta_syncing"
    QUIESCED = "quiesced"
    FINAL_SYNCING = "final_syncing"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ChecksumAlgorithm(str, Enum):
    """Supported checksum algorithms for data integrity verification."""

    SHA256 = "sha256"
    MD5 = "md5"
    XXH3 = "xxh3"


class ChecksumRecord(BaseModel):
    """Checksum for a single data unit (volume, block range, database)."""

    target: str = Field(description="What was checksummed (volume name, db name, etc.)")
    algorithm: ChecksumAlgorithm = Field(default=ChecksumAlgorithm.SHA256)
    source_checksum: str = Field(default="", description="Checksum computed on source")
    target_checksum: str = Field(default="", description="Checksum computed on target after transfer")
    verified: bool = Field(default=False, description="True if source == target checksum")
    verified_at: datetime | None = Field(default=None, description="When verification ran")
    size_bytes: int = Field(default=0, description="Size of the checksummed data")


class ReplicationState(BaseModel):
    """Tracks the replication lifecycle for a single resource.

    Each resource (volume, database, boot disk) gets its own ReplicationState
    that is updated as it moves through sync phases.
    """

    id: UUID = Field(default_factory=uuid4, description="Unique replication tracking ID")
    resource_id: UUID = Field(description="Source resource UUID being replicated")
    resource_name: str = Field(default="", description="Human-readable resource name")
    status: ReplicationStatus = Field(default=ReplicationStatus.PENDING)
    last_sync_time: datetime | None = Field(default=None, description="Timestamp of last successful sync")
    data_transferred_bytes: int = Field(default=0, description="Total bytes transferred so far")
    data_total_bytes: int = Field(default=0, description="Total bytes to transfer")
    checksums: list[ChecksumRecord] = Field(default_factory=list, description="Checksum records for verification")
    checksum_verified: bool = Field(default=False, description="True if all checksums passed")
    checkpoint_id: str | None = Field(default=None, description="Last checkpoint covering this resource")
    error: str | None = Field(default=None, description="Error message if replication failed")
    retry_count: int = Field(default=0, description="Number of retries attempted")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def mark_syncing(self) -> None:
        """Transition to syncing state."""
        self.status = ReplicationStatus.SYNCING
        self.updated_at = datetime.now(timezone.utc)

    def mark_completed(self, transferred_bytes: int) -> None:
        """Transition to completed state with final transfer count."""
        self.status = ReplicationStatus.COMPLETED
        self.data_transferred_bytes = transferred_bytes
        self.last_sync_time = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def mark_failed(self, error: str) -> None:
        """Transition to failed state."""
        self.status = ReplicationStatus.FAILED
        self.error = error
        self.updated_at = datetime.now(timezone.utc)

    def record_checksum(self, record: ChecksumRecord) -> None:
        """Add a checksum record and update the verified flag."""
        self.checksums.append(record)
        self.checksum_verified = all(c.verified for c in self.checksums)
        self.updated_at = datetime.now(timezone.utc)


class CheckpointStatus(str, Enum):
    """Status of an execution checkpoint."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    USED_FOR_RESUME = "used_for_resume"
    EXPIRED = "expired"


class ExecutionCheckpoint(BaseModel):
    """Workflow-level checkpoint for resume and recovery.

    Captures the state of an entire migration workflow at a point in time,
    enabling resume from the last successful stage after failure.
    """

    checkpoint_id: str = Field(
        default_factory=lambda: f"excp-{uuid4().hex[:12]}",
        description="Unique checkpoint identifier",
    )
    workflow_id: str = Field(description="Migration job/workflow this checkpoint belongs to")
    stage: str = Field(description="Pipeline stage at checkpoint (e.g., 'incremental_sync', 'quiesce')")
    resource_ids: list[UUID] = Field(
        default_factory=list,
        description="Resources covered by this checkpoint",
    )
    replication_states: list[ReplicationState] = Field(
        default_factory=list,
        description="Snapshot of replication states at checkpoint time",
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: CheckpointStatus = Field(default=CheckpointStatus.ACTIVE)
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Arbitrary metadata (db WAL positions, plan_id, etc.)",
    )

    def supersede(self) -> None:
        """Mark this checkpoint as superseded by a newer one."""
        self.status = CheckpointStatus.SUPERSEDED

    def mark_used(self) -> None:
        """Mark this checkpoint as consumed for resume."""
        self.status = CheckpointStatus.USED_FOR_RESUME
