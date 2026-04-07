"""Advanced data migration service — incremental sync, database replication, migration hooks.

Provides:
1. Incremental sync — dirty block tracking, delta transfers, bandwidth estimation
2. Database replication — pg_dump/mysqldump simulation, WAL shipping abstraction
3. Migration hooks — pre/post hooks (quiesce, cutover, rollback checkpoints)
4. Checksum validation — SHA-256 integrity verification per volume/database
5. Checkpoint persistence — save/load plans for resume & recovery
"""

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, Field

from app.models.canonical import ComputeResource, StorageVolume
from app.models.replication import (
    ChecksumAlgorithm,
    ChecksumRecord,
    CheckpointStatus,
    ExecutionCheckpoint,
    ReplicationState,
    ReplicationStatus,
)
from app.models.responses import DiscoveredResources
from app.models.vpc import VPCTranslationResult

logger = structlog.get_logger(__name__)


class SyncMode(str, Enum):
    """Data sync strategy."""

    FULL = "full"
    INCREMENTAL = "incremental"
    DATABASE = "database"


class MigrationPhase(str, Enum):
    """Lifecycle phase of a data migration."""

    IDLE = "idle"
    PRE_SYNC = "pre_sync"
    INITIAL_SYNC = "initial_sync"
    INCREMENTAL_SYNC = "incremental_sync"
    QUIESCE = "quiesce"
    FINAL_SYNC = "final_sync"
    CUTOVER = "cutover"
    VALIDATE = "validate"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class BlockSyncState(BaseModel):
    """Tracks dirty block state for incremental sync."""

    volume_name: str = Field(description="Source volume name")
    volume_id: str = Field(description="Source volume UUID")
    total_blocks: int = Field(default=0, description="Total block count")
    dirty_blocks: int = Field(default=0, description="Blocks changed since last sync")
    synced_blocks: int = Field(default=0, description="Blocks transferred so far")
    block_size_kb: int = Field(default=4096, description="Block size in KB (4MB default)")
    total_size_gb: float = Field(default=0.0, description="Total volume size in GB")
    delta_size_mb: float = Field(default=0.0, description="Size of dirty blocks in MB")


class BandwidthEstimate(BaseModel):
    """Bandwidth and time estimation for a sync operation."""

    total_data_gb: float = Field(description="Total data to transfer in GB")
    delta_data_gb: float = Field(description="Incremental delta in GB")
    estimated_bandwidth_mbps: float = Field(default=1000.0, description="Available bandwidth in Mbps")
    estimated_full_sync_seconds: float = Field(description="Estimated time for full sync")
    estimated_delta_sync_seconds: float = Field(description="Estimated time for delta sync")
    compression_ratio: float = Field(default=0.6, description="Expected compression ratio")


class DatabaseReplicationConfig(BaseModel):
    """Configuration for database-aware migration."""

    db_type: str = Field(description="Database type (postgresql, mysql, mssql)")
    db_name: str = Field(description="Database name")
    source_host: str = Field(description="Source database host")
    method: str = Field(description="Replication method (dump_restore, wal_shipping, logical)")
    estimated_size_gb: float = Field(default=0.0, description="Estimated database size")


class DatabaseReplicationState(BaseModel):
    """State of a database replication operation."""

    config: DatabaseReplicationConfig = Field(description="Replication configuration")
    dump_completed: bool = Field(default=False, description="Whether dump phase completed")
    wal_position: str = Field(default="", description="Last WAL/binlog position synced")
    restore_completed: bool = Field(default=False, description="Whether restore completed")
    tables_migrated: int = Field(default=0, description="Number of tables migrated")
    rows_migrated: int = Field(default=0, description="Total rows migrated")


class MigrationHook(BaseModel):
    """A pre/post migration hook."""

    name: str = Field(description="Hook name")
    phase: str = Field(description="Phase this hook runs in (pre_sync, quiesce, cutover, etc.)")
    command: str = Field(description="Command or action to execute")
    executed: bool = Field(default=False)
    success: bool | None = Field(default=None)
    output: str = Field(default="")
    executed_at: str | None = Field(default=None)


class RollbackCheckpoint(BaseModel):
    """A snapshot point for rollback capability."""

    checkpoint_id: str = Field(description="Unique checkpoint identifier")
    phase: MigrationPhase = Field(description="Phase when checkpoint was created")
    created_at: str = Field(description="ISO timestamp")
    volumes_snapshotted: list[str] = Field(default_factory=list)
    db_wal_position: str = Field(default="", description="DB WAL position at checkpoint")
    description: str = Field(default="")


class DataMigrationPlan(BaseModel):
    """Complete plan for migrating data from source to target."""

    plan_id: str = Field(description="Unique plan identifier")
    job_id: str = Field(default="", description="Associated migration job ID")
    created_at: str = Field(description="ISO timestamp")
    sync_mode: SyncMode = Field(description="Primary sync strategy")
    phase: MigrationPhase = Field(default=MigrationPhase.IDLE)
    block_sync_states: list[BlockSyncState] = Field(default_factory=list)
    bandwidth_estimate: BandwidthEstimate | None = Field(default=None)
    db_replications: list[DatabaseReplicationState] = Field(default_factory=list)
    hooks: list[MigrationHook] = Field(default_factory=list)
    checkpoints: list[RollbackCheckpoint] = Field(default_factory=list)
    phases_completed: list[str] = Field(default_factory=list)
    error: str | None = Field(default=None)
    # Phase 5.1 additions
    replication_states: list[ReplicationState] = Field(
        default_factory=list,
        description="Per-resource replication tracking with checksum verification",
    )
    execution_checkpoints: list[ExecutionCheckpoint] = Field(
        default_factory=list,
        description="Workflow-level checkpoints for resume & recovery",
    )
    checksum_records: list[ChecksumRecord] = Field(
        default_factory=list,
        description="Aggregated checksum verification results",
    )
    dry_run: bool = Field(default=False, description="If True, no actual data was transferred")


class AdvancedDataMigrationService:
    """Orchestrates advanced data migration with incremental sync, DB replication, and hooks.

    Usage:
        service = AdvancedDataMigrationService()
        plan = service.plan(canonical, vpc_result, strategy_assignments)
        plan = service.execute_pre_hooks(plan)
        plan = service.initial_sync(plan)
        plan = service.incremental_sync(plan)
        plan = service.quiesce(plan)
        plan = service.final_sync(plan)
        plan = service.cutover(plan)
        plan = service.validate(plan)

    Resume:
        plan = service.load_plan(job_id)
        plan = service.resume(plan)  # continues from last checkpoint
    """

    # Ordered pipeline stages for resume logic
    PIPELINE_STAGES = [
        "pre_hooks", "initial_sync", "incremental_sync",
        "quiesce", "final_sync", "cutover", "validate",
    ]

    def __init__(
        self,
        output_dir: str | Path = "output/migrations",
        bandwidth_mbps: float = 1000.0,
        compression_ratio: float = 0.6,
        checksum_algorithm: ChecksumAlgorithm = ChecksumAlgorithm.SHA256,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._bandwidth_mbps = bandwidth_mbps
        self._compression_ratio = compression_ratio
        self._checksum_algorithm = checksum_algorithm

    def plan(
        self,
        canonical: DiscoveredResources,
        vpc_result: VPCTranslationResult | None = None,
        strategy_assignments: dict[str, str] | None = None,
    ) -> DataMigrationPlan:
        """Create a data migration plan with block sync states and bandwidth estimates.

        Analyzes source volumes to determine sync mode, block counts, and transfer estimates.
        Detects databases from compute metadata to set up replication configs.
        """
        strategies = strategy_assignments or {}

        # Determine overall sync mode
        has_db = any(
            self._detect_database(vm) for vm in canonical.compute
        )
        sync_mode = SyncMode.DATABASE if has_db else SyncMode.INCREMENTAL

        # Build block sync states for all storage volumes
        block_states = self._build_block_sync_states(canonical.storage, canonical.compute)

        # Build database replication configs
        db_replications = self._build_db_replications(canonical.compute)

        # Estimate bandwidth
        total_data_gb = sum(bs.total_size_gb for bs in block_states)
        delta_data_gb = sum(bs.delta_size_mb / 1024 for bs in block_states)
        bandwidth_estimate = self._estimate_bandwidth(total_data_gb, delta_data_gb)

        # Build standard hooks
        hooks = self._build_default_hooks(canonical.compute, db_replications)

        # Build per-resource replication states
        replication_states = self._build_replication_states(
            canonical.compute, canonical.storage, block_states
        )

        plan = DataMigrationPlan(
            plan_id=f"dmp-{uuid4().hex[:12]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            sync_mode=sync_mode,
            block_sync_states=block_states,
            bandwidth_estimate=bandwidth_estimate,
            db_replications=db_replications,
            hooks=hooks,
            replication_states=replication_states,
        )

        logger.info(
            "data_migration_planned",
            plan_id=plan.plan_id,
            sync_mode=sync_mode.value,
            volumes=len(block_states),
            total_data_gb=round(total_data_gb, 1),
            delta_data_gb=round(delta_data_gb, 1),
            db_replications=len(db_replications),
            hooks=len(hooks),
            replication_states=len(replication_states),
        )

        return plan

    def initial_sync(self, plan: DataMigrationPlan) -> DataMigrationPlan:
        """Perform initial full sync of all volumes."""
        plan.phase = MigrationPhase.INITIAL_SYNC

        for bs in plan.block_sync_states:
            # Simulate full sync — all blocks transferred
            bs.synced_blocks = bs.total_blocks
            bs.dirty_blocks = int(bs.total_blocks * 0.05)  # 5% changed during sync

        # Update replication states
        for rs in plan.replication_states:
            rs.status = ReplicationStatus.SYNCING
            rs.data_transferred_bytes = int(rs.data_total_bytes * 0.95)
            rs.last_sync_time = datetime.now(timezone.utc)
            rs.updated_at = datetime.now(timezone.utc)

        plan.phases_completed.append("initial_sync")

        logger.info(
            "initial_sync_completed",
            plan_id=plan.plan_id,
            volumes=len(plan.block_sync_states),
            total_gb=sum(bs.total_size_gb for bs in plan.block_sync_states),
        )
        return plan

    def incremental_sync(self, plan: DataMigrationPlan) -> DataMigrationPlan:
        """Perform incremental delta sync of dirty blocks."""
        plan.phase = MigrationPhase.INCREMENTAL_SYNC

        total_delta_mb = 0.0
        for bs in plan.block_sync_states:
            # Transfer dirty blocks
            delta_mb = (bs.dirty_blocks * bs.block_size_kb) / 1024
            total_delta_mb += delta_mb
            bs.synced_blocks = bs.total_blocks
            bs.delta_size_mb = delta_mb
            bs.dirty_blocks = int(bs.dirty_blocks * 0.1)  # 90% reduction after sync

        # Update replication states
        for rs in plan.replication_states:
            rs.status = ReplicationStatus.DELTA_SYNCING
            rs.data_transferred_bytes = rs.data_total_bytes
            rs.last_sync_time = datetime.now(timezone.utc)
            rs.updated_at = datetime.now(timezone.utc)

        plan.phases_completed.append("incremental_sync")

        # Create a rollback checkpoint after incremental sync
        checkpoint = RollbackCheckpoint(
            checkpoint_id=f"ckpt-{uuid4().hex[:8]}",
            phase=MigrationPhase.INCREMENTAL_SYNC,
            created_at=datetime.now(timezone.utc).isoformat(),
            volumes_snapshotted=[bs.volume_name for bs in plan.block_sync_states],
            description="Post-incremental-sync checkpoint",
        )
        plan.checkpoints.append(checkpoint)

        # Create an execution checkpoint for resume capability
        exec_checkpoint = self._create_execution_checkpoint(
            plan, "incremental_sync", checkpoint.checkpoint_id
        )
        plan.execution_checkpoints.append(exec_checkpoint)

        # Persist plan to disk for recovery
        self._persist_checkpoint(plan)

        logger.info(
            "incremental_sync_completed",
            plan_id=plan.plan_id,
            delta_mb=round(total_delta_mb, 1),
            checkpoint_id=checkpoint.checkpoint_id,
            exec_checkpoint_id=exec_checkpoint.checkpoint_id,
        )
        return plan

    def execute_pre_hooks(self, plan: DataMigrationPlan) -> DataMigrationPlan:
        """Execute pre-migration hooks."""
        plan.phase = MigrationPhase.PRE_SYNC

        for hook in plan.hooks:
            if hook.phase == "pre_sync":
                hook.executed = True
                hook.success = True
                hook.output = f"Simulated: {hook.command}"
                hook.executed_at = datetime.now(timezone.utc).isoformat()

        plan.phases_completed.append("pre_hooks")

        logger.info(
            "pre_hooks_executed",
            plan_id=plan.plan_id,
            hooks_run=sum(1 for h in plan.hooks if h.phase == "pre_sync" and h.executed),
        )
        return plan

    def quiesce(self, plan: DataMigrationPlan) -> DataMigrationPlan:
        """Quiesce source workloads for final consistent sync."""
        plan.phase = MigrationPhase.QUIESCE

        # Execute quiesce hooks
        for hook in plan.hooks:
            if hook.phase == "quiesce":
                hook.executed = True
                hook.success = True
                hook.output = f"Simulated: {hook.command}"
                hook.executed_at = datetime.now(timezone.utc).isoformat()

        # Flush database WAL/binlog
        for db_state in plan.db_replications:
            db_state.wal_position = f"0/{uuid4().hex[:8].upper()}"

        # Update replication states
        for rs in plan.replication_states:
            rs.status = ReplicationStatus.QUIESCED
            rs.updated_at = datetime.now(timezone.utc)

        # Create quiesce checkpoint
        checkpoint = RollbackCheckpoint(
            checkpoint_id=f"ckpt-{uuid4().hex[:8]}",
            phase=MigrationPhase.QUIESCE,
            created_at=datetime.now(timezone.utc).isoformat(),
            volumes_snapshotted=[bs.volume_name for bs in plan.block_sync_states],
            db_wal_position=plan.db_replications[0].wal_position if plan.db_replications else "",
            description="Pre-cutover quiesce checkpoint (rollback target)",
        )
        plan.checkpoints.append(checkpoint)

        # Execution checkpoint for resume
        exec_checkpoint = self._create_execution_checkpoint(
            plan, "quiesce", checkpoint.checkpoint_id
        )
        plan.execution_checkpoints.append(exec_checkpoint)
        self._persist_checkpoint(plan)

        plan.phases_completed.append("quiesce")

        logger.info(
            "quiesce_completed",
            plan_id=plan.plan_id,
            checkpoint_id=checkpoint.checkpoint_id,
            exec_checkpoint_id=exec_checkpoint.checkpoint_id,
            db_wal_positions=[d.wal_position for d in plan.db_replications],
        )
        return plan

    def final_sync(self, plan: DataMigrationPlan) -> DataMigrationPlan:
        """Final delta sync after quiesce — minimal data remaining."""
        plan.phase = MigrationPhase.FINAL_SYNC

        total_final_mb = 0.0
        for bs in plan.block_sync_states:
            # Very small delta after quiesce
            delta_mb = (bs.dirty_blocks * bs.block_size_kb) / 1024
            total_final_mb += delta_mb
            bs.synced_blocks = bs.total_blocks
            bs.delta_size_mb = delta_mb
            bs.dirty_blocks = 0  # Fully caught up

        # Complete database replication
        for db_state in plan.db_replications:
            if not db_state.dump_completed:
                db_state.dump_completed = True
            db_state.restore_completed = True

        plan.phases_completed.append("final_sync")

        logger.info(
            "final_sync_completed",
            plan_id=plan.plan_id,
            final_delta_mb=round(total_final_mb, 1),
        )
        return plan

    def cutover(self, plan: DataMigrationPlan) -> DataMigrationPlan:
        """Execute cutover — switch traffic to target."""
        plan.phase = MigrationPhase.CUTOVER

        # Execute cutover hooks
        for hook in plan.hooks:
            if hook.phase == "cutover":
                hook.executed = True
                hook.success = True
                hook.output = f"Simulated: {hook.command}"
                hook.executed_at = datetime.now(timezone.utc).isoformat()

        plan.phases_completed.append("cutover")

        logger.info("cutover_completed", plan_id=plan.plan_id)
        return plan

    def validate(self, plan: DataMigrationPlan) -> DataMigrationPlan:
        """Validate data integrity post-cutover with checksum verification."""
        plan.phase = MigrationPhase.VALIDATE

        # Execute validation hooks
        for hook in plan.hooks:
            if hook.phase == "validate":
                hook.executed = True
                hook.success = True
                hook.output = f"Simulated: {hook.command}"
                hook.executed_at = datetime.now(timezone.utc).isoformat()

        # Checksum verification for each volume
        checksum_records = self._verify_checksums(plan)
        plan.checksum_records.extend(checksum_records)

        # Update replication states with checksum results
        for rs in plan.replication_states:
            rs.status = ReplicationStatus.VALIDATING
            # Match checksums to replication states by resource name
            matching = [c for c in checksum_records if c.target == rs.resource_name]
            for cr in matching:
                rs.record_checksum(cr)
            rs.status = ReplicationStatus.COMPLETED
            rs.updated_at = datetime.now(timezone.utc)

        all_verified = all(cr.verified for cr in checksum_records) if checksum_records else True
        if not all_verified:
            failed = [cr.target for cr in checksum_records if not cr.verified]
            plan.error = f"Checksum verification failed for: {', '.join(failed)}"
            logger.warning(
                "checksum_verification_failed",
                plan_id=plan.plan_id,
                failed_targets=failed,
            )

        plan.phase = MigrationPhase.COMPLETED
        plan.phases_completed.append("validate")

        logger.info(
            "data_migration_validated",
            plan_id=plan.plan_id,
            checksums_verified=len(checksum_records),
            all_passed=all_verified,
        )
        return plan

    def rollback(self, plan: DataMigrationPlan) -> DataMigrationPlan:
        """Rollback to the most recent checkpoint."""
        if not plan.checkpoints:
            plan.error = "No checkpoints available for rollback"
            plan.phase = MigrationPhase.FAILED
            return plan

        latest = plan.checkpoints[-1]
        plan.phase = MigrationPhase.ROLLED_BACK

        # Execute rollback hooks (cutover hooks in reverse)
        for hook in plan.hooks:
            if hook.phase == "rollback":
                hook.executed = True
                hook.success = True
                hook.output = f"Simulated rollback: {hook.command}"
                hook.executed_at = datetime.now(timezone.utc).isoformat()

        plan.phases_completed.append(f"rollback_to_{latest.checkpoint_id}")

        logger.info(
            "rollback_completed",
            plan_id=plan.plan_id,
            checkpoint_id=latest.checkpoint_id,
            checkpoint_phase=latest.phase.value,
        )
        return plan

    def write_plan(self, plan: DataMigrationPlan, job_id: str = "") -> Path:
        """Write the migration plan to disk as JSON."""
        output_dir = self._output_dir / (job_id or plan.plan_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        plan_path = output_dir / "data_migration_plan.json"
        plan_path.write_text(
            json.dumps(plan.model_dump(mode="json"), indent=2, default=str)
        )

        logger.info(
            "data_migration_plan_written",
            plan_id=plan.plan_id,
            path=str(plan_path),
        )
        return plan_path

    # --- Resume & Recovery ---

    def load_plan(self, job_id: str) -> DataMigrationPlan | None:
        """Load a persisted migration plan from disk for resume.

        Args:
            job_id: The job ID whose plan to load.

        Returns:
            The deserialized DataMigrationPlan, or None if not found.
        """
        plan_path = self._output_dir / job_id / "data_migration_plan.json"
        if not plan_path.exists():
            logger.warning("plan_not_found", job_id=job_id, path=str(plan_path))
            return None

        raw = json.loads(plan_path.read_text())
        plan = DataMigrationPlan.model_validate(raw)

        logger.info(
            "plan_loaded",
            plan_id=plan.plan_id,
            job_id=job_id,
            phase=plan.phase.value,
            phases_completed=plan.phases_completed,
        )
        return plan

    def resume(self, plan: DataMigrationPlan) -> DataMigrationPlan:
        """Resume a migration plan from the last completed stage.

        Determines which stages have been completed and continues
        from the next stage in the pipeline.

        Args:
            plan: A previously persisted plan (loaded via load_plan).

        Returns:
            The plan after completing all remaining stages.
        """
        completed = set(plan.phases_completed)

        # Mark the latest execution checkpoint as used for resume
        if plan.execution_checkpoints:
            latest = plan.execution_checkpoints[-1]
            latest.mark_used()

        logger.info(
            "migration_resume_started",
            plan_id=plan.plan_id,
            completed_stages=list(completed),
        )

        # Map stage names to methods
        stage_methods = {
            "pre_hooks": self.execute_pre_hooks,
            "initial_sync": self.initial_sync,
            "incremental_sync": self.incremental_sync,
            "quiesce": self.quiesce,
            "final_sync": self.final_sync,
            "cutover": self.cutover,
            "validate": self.validate,
        }

        for stage in self.PIPELINE_STAGES:
            if stage not in completed:
                logger.info("resume_executing_stage", plan_id=plan.plan_id, stage=stage)
                plan = stage_methods[stage](plan)

        return plan

    # --- Checksum Verification ---

    def _verify_checksums(self, plan: DataMigrationPlan) -> list[ChecksumRecord]:
        """Compute and verify checksums for all synced volumes and databases."""
        records: list[ChecksumRecord] = []

        for bs in plan.block_sync_states:
            # Simulate checksum computation (in production, this would read actual data)
            source_hash = self._simulate_checksum(bs.volume_name, bs.total_size_gb, "source")
            target_hash = self._simulate_checksum(bs.volume_name, bs.total_size_gb, "target")

            record = ChecksumRecord(
                target=bs.volume_name,
                algorithm=self._checksum_algorithm,
                source_checksum=source_hash,
                target_checksum=target_hash,
                verified=source_hash == target_hash,
                verified_at=datetime.now(timezone.utc),
                size_bytes=int(bs.total_size_gb * 1024 * 1024 * 1024),
            )
            records.append(record)

        for db_state in plan.db_replications:
            db_name = db_state.config.db_name
            source_hash = self._simulate_checksum(db_name, db_state.config.estimated_size_gb, "source")
            target_hash = self._simulate_checksum(db_name, db_state.config.estimated_size_gb, "target")

            record = ChecksumRecord(
                target=db_name,
                algorithm=self._checksum_algorithm,
                source_checksum=source_hash,
                target_checksum=target_hash,
                verified=source_hash == target_hash,
                verified_at=datetime.now(timezone.utc),
                size_bytes=int(db_state.config.estimated_size_gb * 1024 * 1024 * 1024),
            )
            records.append(record)

        return records

    @staticmethod
    def _simulate_checksum(name: str, size_gb: float, side: str) -> str:
        """Generate a deterministic simulated checksum.

        In production, this would compute a real SHA-256 over the data.
        For simulation, we use a deterministic hash so source == target (data match).
        """
        raw = f"{name}:{size_gb}"
        return hashlib.sha256(raw.encode()).hexdigest()

    # --- Replication State Tracking ---

    def _build_replication_states(
        self,
        compute: list[ComputeResource],
        storage: list[StorageVolume],
        block_states: list[BlockSyncState],
    ) -> list[ReplicationState]:
        """Build per-resource ReplicationState entries for all migrating resources."""
        states: list[ReplicationState] = []

        # Storage volumes
        for vol in storage:
            matching_bs = next(
                (bs for bs in block_states if bs.volume_id == str(vol.id)),
                None,
            )
            states.append(ReplicationState(
                resource_id=vol.id,
                resource_name=vol.name,
                data_total_bytes=int(vol.size_gb * 1024 * 1024 * 1024),
            ))

        # Boot disks from compute
        for vm in compute:
            if vm.storage_gb > 0:
                states.append(ReplicationState(
                    resource_id=vm.id,
                    resource_name=f"{vm.name}-boot",
                    data_total_bytes=int(vm.storage_gb * 1024 * 1024 * 1024),
                ))

        return states

    # --- Execution Checkpoints ---

    def _create_execution_checkpoint(
        self,
        plan: DataMigrationPlan,
        stage: str,
        rollback_checkpoint_id: str = "",
    ) -> ExecutionCheckpoint:
        """Create a workflow-level execution checkpoint."""
        # Supersede previous execution checkpoints
        for prev in plan.execution_checkpoints:
            if prev.status == CheckpointStatus.ACTIVE:
                prev.supersede()

        resource_ids = [rs.resource_id for rs in plan.replication_states]

        checkpoint = ExecutionCheckpoint(
            workflow_id=plan.job_id or plan.plan_id,
            stage=stage,
            resource_ids=resource_ids,
            replication_states=[rs.model_copy(deep=True) for rs in plan.replication_states],
            metadata={
                "plan_id": plan.plan_id,
                "rollback_checkpoint_id": rollback_checkpoint_id,
                "phases_completed": ",".join(plan.phases_completed),
            },
        )

        return checkpoint

    def _persist_checkpoint(self, plan: DataMigrationPlan) -> Path:
        """Persist the current plan state to disk for recovery."""
        output_dir = self._output_dir / (plan.job_id or plan.plan_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        plan_path = output_dir / "data_migration_plan.json"
        plan_path.write_text(
            json.dumps(plan.model_dump(mode="json"), indent=2, default=str)
        )
        return plan_path

    # --- Private helpers ---

    def _detect_database(self, vm: ComputeResource) -> bool:
        """Detect if a compute resource runs a database."""
        db_indicators = ["postgresql", "postgres", "mysql", "mariadb", "sql-server", "mssql", "oracle"]
        search_fields = [
            vm.os.lower(),
            vm.tags.get("app", "").lower(),
            vm.name.lower(),
            vm.metadata.get("annotation", "").lower(),
        ]
        return any(
            indicator in field
            for indicator in db_indicators
            for field in search_fields
        )

    def _detect_db_type(self, vm: ComputeResource) -> str:
        """Determine database type from compute resource metadata."""
        search_text = " ".join([
            vm.os.lower(),
            vm.tags.get("app", "").lower(),
            vm.name.lower(),
        ])
        if "postgresql" in search_text or "postgres" in search_text:
            return "postgresql"
        if "mysql" in search_text or "mariadb" in search_text:
            return "mysql"
        if "sql-server" in search_text or "mssql" in search_text or "sql_server" in search_text:
            return "mssql"
        if "oracle" in search_text:
            return "oracle"
        return "unknown"

    def _build_block_sync_states(
        self,
        storage: list[StorageVolume],
        compute: list[ComputeResource],
    ) -> list[BlockSyncState]:
        """Build block-level sync tracking for each volume."""
        # Also include boot disks from compute
        states: list[BlockSyncState] = []

        # Data volumes
        for vol in storage:
            block_size_kb = 4096  # 4MB blocks
            total_blocks = max(1, (vol.size_gb * 1024 * 1024) // block_size_kb)  # GB → KB → blocks
            # Simulate 10-30% dirty blocks for initial pass
            dirty_ratio = 0.15
            dirty_blocks = int(total_blocks * dirty_ratio)

            states.append(
                BlockSyncState(
                    volume_name=vol.name,
                    volume_id=str(vol.id),
                    total_blocks=total_blocks,
                    dirty_blocks=dirty_blocks,
                    block_size_kb=block_size_kb,
                    total_size_gb=float(vol.size_gb),
                    delta_size_mb=round((dirty_blocks * block_size_kb) / 1024, 1),
                )
            )

        # Boot disks from compute
        for vm in compute:
            if vm.storage_gb > 0:
                block_size_kb = 4096
                total_blocks = max(1, (vm.storage_gb * 1024 * 1024) // block_size_kb)
                dirty_blocks = int(total_blocks * 0.2)

                states.append(
                    BlockSyncState(
                        volume_name=f"{vm.name}-boot",
                        volume_id=str(vm.id),
                        total_blocks=total_blocks,
                        dirty_blocks=dirty_blocks,
                        block_size_kb=block_size_kb,
                        total_size_gb=float(vm.storage_gb),
                        delta_size_mb=round((dirty_blocks * block_size_kb) / 1024, 1),
                    )
                )

        return states

    def _estimate_bandwidth(
        self,
        total_data_gb: float,
        delta_data_gb: float,
    ) -> BandwidthEstimate:
        """Estimate transfer time based on available bandwidth and compression."""
        effective_bandwidth_gbps = (self._bandwidth_mbps / 8) / 1024  # Mbps → GB/s
        compressed_total = total_data_gb * self._compression_ratio
        compressed_delta = delta_data_gb * self._compression_ratio

        full_sync_seconds = compressed_total / max(effective_bandwidth_gbps, 0.001)
        delta_sync_seconds = compressed_delta / max(effective_bandwidth_gbps, 0.001)

        return BandwidthEstimate(
            total_data_gb=round(total_data_gb, 2),
            delta_data_gb=round(delta_data_gb, 2),
            estimated_bandwidth_mbps=self._bandwidth_mbps,
            estimated_full_sync_seconds=round(full_sync_seconds, 1),
            estimated_delta_sync_seconds=round(delta_sync_seconds, 1),
            compression_ratio=self._compression_ratio,
        )

    def _build_db_replications(
        self,
        compute: list[ComputeResource],
    ) -> list[DatabaseReplicationState]:
        """Detect databases from compute resources and build replication configs."""
        replications: list[DatabaseReplicationState] = []

        for vm in compute:
            if not self._detect_database(vm):
                continue

            db_type = self._detect_db_type(vm)

            # Determine replication method based on DB type
            method_map = {
                "postgresql": "wal_shipping",
                "mysql": "logical",
                "mssql": "dump_restore",
                "oracle": "dump_restore",
                "unknown": "dump_restore",
            }

            # Estimate DB size from attached storage
            estimated_size = sum(
                vol_gb for vol_gb in [vm.storage_gb] if vol_gb > 0
            )

            config = DatabaseReplicationConfig(
                db_type=db_type,
                db_name=vm.tags.get("app", vm.name),
                source_host=vm.ip_addresses[0] if vm.ip_addresses else vm.name,
                method=method_map.get(db_type, "dump_restore"),
                estimated_size_gb=float(estimated_size),
            )

            replications.append(
                DatabaseReplicationState(
                    config=config,
                    tables_migrated=0,
                    rows_migrated=0,
                )
            )

        return replications

    def _build_default_hooks(
        self,
        compute: list[ComputeResource],
        db_replications: list[DatabaseReplicationState],
    ) -> list[MigrationHook]:
        """Build standard pre/post migration hooks."""
        hooks: list[MigrationHook] = []

        # Pre-sync hooks
        hooks.append(MigrationHook(
            name="verify-source-connectivity",
            phase="pre_sync",
            command="ping -c 3 source_hosts && ssh source_hosts 'uptime'",
        ))
        hooks.append(MigrationHook(
            name="create-pre-migration-snapshot",
            phase="pre_sync",
            command="lvcreate --snapshot --size 10G --name pre-migration-snap",
        ))

        # Quiesce hooks
        for vm in compute:
            if vm.stateful:
                hooks.append(MigrationHook(
                    name=f"quiesce-{vm.name}",
                    phase="quiesce",
                    command=f"ssh {vm.ip_addresses[0] if vm.ip_addresses else vm.name} 'sync && echo 3 > /proc/sys/vm/drop_caches'",
                ))

        # Database-specific quiesce
        for db_state in db_replications:
            db = db_state.config
            if db.db_type == "postgresql":
                hooks.append(MigrationHook(
                    name=f"pg-checkpoint-{db.db_name}",
                    phase="quiesce",
                    command=f"psql -h {db.source_host} -c 'CHECKPOINT; SELECT pg_switch_wal();'",
                ))
            elif db.db_type == "mysql":
                hooks.append(MigrationHook(
                    name=f"mysql-flush-{db.db_name}",
                    phase="quiesce",
                    command=f"mysql -h {db.source_host} -e 'FLUSH TABLES WITH READ LOCK; SHOW MASTER STATUS;'",
                ))
            elif db.db_type == "mssql":
                hooks.append(MigrationHook(
                    name=f"mssql-backup-{db.db_name}",
                    phase="quiesce",
                    command=f"sqlcmd -S {db.source_host} -Q \"BACKUP DATABASE [{db.db_name}] TO DISK='NUL' WITH COPY_ONLY\"",
                ))

        # Cutover hooks
        hooks.append(MigrationHook(
            name="update-dns-records",
            phase="cutover",
            command="nsupdate -k /etc/dns/migration.key <<< 'update delete old.example.com A'",
        ))
        hooks.append(MigrationHook(
            name="update-load-balancer",
            phase="cutover",
            command="ibmcloud is lb-pool-member-update --pool migration-pool --target target-vsi",
        ))

        # Rollback hooks
        hooks.append(MigrationHook(
            name="revert-dns-records",
            phase="rollback",
            command="nsupdate -k /etc/dns/migration.key <<< 'update add old.example.com A source_ip'",
        ))
        hooks.append(MigrationHook(
            name="revert-load-balancer",
            phase="rollback",
            command="ibmcloud is lb-pool-member-update --pool migration-pool --target source-vsi",
        ))

        # Validation hooks
        hooks.append(MigrationHook(
            name="verify-target-connectivity",
            phase="validate",
            command="ping -c 3 target_hosts && curl -s https://target_host/health",
        ))
        hooks.append(MigrationHook(
            name="verify-data-integrity",
            phase="validate",
            command="md5sum --check /tmp/migration-checksums.md5",
        ))

        return hooks
