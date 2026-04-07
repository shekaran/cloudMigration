"""Replication engine — continuous delta sync, parallel sync, and cutover optimization.

Provides:
1. Continuous delta sync — CDC-like change tracking with configurable intervals
2. Parallel sync — concurrent volume synchronization with throttling
3. Cutover optimization — minimize downtime window through pre-staging
"""

import asyncio
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, Field

from app.models.replication import (
    ChecksumAlgorithm,
    ChecksumRecord,
    ExecutionCheckpoint,
    ReplicationState,
    ReplicationStatus,
)

logger = structlog.get_logger(__name__)


class CDCMode(str, Enum):
    """Change data capture mode for continuous sync."""

    LOG_BASED = "log_based"
    TRIGGER_BASED = "trigger_based"
    TIMESTAMP_BASED = "timestamp_based"
    BLOCK_DIFF = "block_diff"


class SyncPriority(str, Enum):
    """Priority level for parallel sync scheduling."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class ContinuousSyncConfig(BaseModel):
    """Configuration for continuous delta sync."""

    mode: CDCMode = Field(default=CDCMode.BLOCK_DIFF, description="CDC mode")
    interval_seconds: float = Field(default=30.0, description="Sync interval in seconds")
    max_iterations: int = Field(default=100, description="Max sync iterations before auto-cutover")
    convergence_threshold_mb: float = Field(
        default=50.0,
        description="Delta size below which to trigger cutover readiness",
    )
    max_lag_seconds: float = Field(
        default=300.0,
        description="Maximum acceptable replication lag before alert",
    )


class ParallelSyncConfig(BaseModel):
    """Configuration for parallel volume synchronization."""

    max_concurrent: int = Field(default=4, description="Maximum concurrent sync operations")
    bandwidth_limit_mbps: float = Field(default=0.0, description="Per-stream bandwidth limit (0=unlimited)")
    priority_order: list[SyncPriority] = Field(
        default_factory=lambda: [
            SyncPriority.CRITICAL,
            SyncPriority.HIGH,
            SyncPriority.NORMAL,
            SyncPriority.LOW,
        ],
    )


class CutoverConfig(BaseModel):
    """Configuration for cutover optimization."""

    max_downtime_seconds: float = Field(default=300.0, description="Maximum acceptable downtime")
    pre_stage_final_sync: bool = Field(default=True, description="Pre-stage as much data as possible")
    parallel_cutover: bool = Field(default=True, description="Cut over resources in parallel")
    verification_timeout_seconds: float = Field(default=60.0, description="Post-cutover verification timeout")


class SyncIteration(BaseModel):
    """Record of a single continuous sync iteration."""

    iteration: int = Field(description="Iteration number")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = Field(default=None)
    delta_mb: float = Field(default=0.0, description="Data transferred in this iteration")
    dirty_blocks: int = Field(default=0, description="Dirty blocks at start of iteration")
    blocks_synced: int = Field(default=0, description="Blocks synced in this iteration")
    lag_seconds: float = Field(default=0.0, description="Replication lag at end of iteration")
    converged: bool = Field(default=False, description="True if delta below threshold")


class VolumeSyncTask(BaseModel):
    """A single volume sync task for parallel execution."""

    task_id: str = Field(default_factory=lambda: f"vst-{uuid4().hex[:8]}")
    volume_name: str = Field(description="Volume being synced")
    resource_id: UUID = Field(description="Resource UUID")
    priority: SyncPriority = Field(default=SyncPriority.NORMAL)
    size_gb: float = Field(default=0.0)
    status: str = Field(default="pending")
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    transferred_gb: float = Field(default=0.0)
    error: str | None = Field(default=None)


class CutoverPlan(BaseModel):
    """Optimized cutover plan to minimize downtime."""

    cutover_id: str = Field(default_factory=lambda: f"cut-{uuid4().hex[:8]}")
    estimated_downtime_seconds: float = Field(default=0.0)
    pre_staged_gb: float = Field(default=0.0)
    remaining_delta_mb: float = Field(default=0.0)
    resources_to_cut: list[str] = Field(default_factory=list)
    parallel_groups: list[list[str]] = Field(
        default_factory=list,
        description="Groups of resources that can be cut over simultaneously",
    )
    ready: bool = Field(default=False)


class ReplicationEngineResult(BaseModel):
    """Result of a replication engine run."""

    sync_iterations: list[SyncIteration] = Field(default_factory=list)
    parallel_tasks: list[VolumeSyncTask] = Field(default_factory=list)
    cutover_plan: CutoverPlan | None = Field(default=None)
    replication_states: list[ReplicationState] = Field(default_factory=list)
    total_data_transferred_gb: float = Field(default=0.0)
    final_delta_mb: float = Field(default=0.0)
    converged: bool = Field(default=False)
    iterations_completed: int = Field(default=0)


class ReplicationEngine:
    """Manages continuous delta sync, parallel sync, and optimized cutover.

    Usage:
        engine = ReplicationEngine()
        result = await engine.run_continuous_sync(replication_states, config)
        tasks = await engine.run_parallel_sync(replication_states, config)
        cutover = engine.plan_cutover(replication_states, config)
    """

    def __init__(
        self,
        continuous_config: ContinuousSyncConfig | None = None,
        parallel_config: ParallelSyncConfig | None = None,
        cutover_config: CutoverConfig | None = None,
    ) -> None:
        self._continuous = continuous_config or ContinuousSyncConfig()
        self._parallel = parallel_config or ParallelSyncConfig()
        self._cutover = cutover_config or CutoverConfig()

    async def run_continuous_sync(
        self,
        replication_states: list[ReplicationState],
        config: ContinuousSyncConfig | None = None,
    ) -> ReplicationEngineResult:
        """Run continuous delta sync until convergence or max iterations.

        Simulates CDC-like behavior: each iteration syncs dirty blocks,
        tracks convergence, and stops when delta drops below threshold.
        """
        cfg = config or self._continuous
        result = ReplicationEngineResult(
            replication_states=[rs.model_copy(deep=True) for rs in replication_states],
        )

        # Simulate initial dirty state
        dirty_per_resource: dict[UUID, int] = {}
        for rs in replication_states:
            # Estimate dirty blocks based on data size (15% initial)
            total_blocks = max(1, rs.data_total_bytes // (4096 * 1024))  # 4MB blocks
            dirty_per_resource[rs.resource_id] = int(total_blocks * 0.15)
            rs.status = ReplicationStatus.SYNCING

        total_transferred = 0.0

        for iteration in range(1, cfg.max_iterations + 1):
            iter_record = SyncIteration(iteration=iteration)
            iter_delta_mb = 0.0
            total_dirty = 0

            for rs in replication_states:
                dirty = dirty_per_resource.get(rs.resource_id, 0)
                total_dirty += dirty

                # Transfer dirty blocks
                delta_mb = (dirty * 4096) / 1024  # 4MB blocks → MB
                iter_delta_mb += delta_mb

                # After sync, new changes accumulate (diminishing)
                # Each iteration produces ~10% of previous dirty blocks
                new_dirty = max(1, int(dirty * 0.1))
                dirty_per_resource[rs.resource_id] = new_dirty

                # Update replication state
                rs.data_transferred_bytes += int(delta_mb * 1024 * 1024)
                rs.last_sync_time = datetime.now(timezone.utc)

            iter_record.dirty_blocks = total_dirty
            iter_record.blocks_synced = total_dirty
            iter_record.delta_mb = round(iter_delta_mb, 2)
            iter_record.completed_at = datetime.now(timezone.utc)
            iter_record.lag_seconds = round(iter_delta_mb / max(1.0, 125.0), 2)  # ~1Gbps assumed
            iter_record.converged = iter_delta_mb < cfg.convergence_threshold_mb

            result.sync_iterations.append(iter_record)
            total_transferred += iter_delta_mb / 1024  # MB → GB

            if iter_record.converged:
                logger.info(
                    "continuous_sync_converged",
                    iteration=iteration,
                    final_delta_mb=round(iter_delta_mb, 2),
                    threshold_mb=cfg.convergence_threshold_mb,
                )
                break

            # Simulate sync interval (shortened for simulation)
            await asyncio.sleep(0.01)

        result.total_data_transferred_gb = round(total_transferred, 3)
        result.final_delta_mb = round(result.sync_iterations[-1].delta_mb if result.sync_iterations else 0.0, 2)
        result.converged = result.sync_iterations[-1].converged if result.sync_iterations else False
        result.iterations_completed = len(result.sync_iterations)

        # Update final replication states
        for rs in replication_states:
            rs.status = ReplicationStatus.DELTA_SYNCING if not result.converged else ReplicationStatus.QUIESCED
            rs.updated_at = datetime.now(timezone.utc)

        result.replication_states = [rs.model_copy(deep=True) for rs in replication_states]

        logger.info(
            "continuous_sync_completed",
            iterations=result.iterations_completed,
            total_transferred_gb=result.total_data_transferred_gb,
            converged=result.converged,
            final_delta_mb=result.final_delta_mb,
        )
        return result

    async def run_parallel_sync(
        self,
        replication_states: list[ReplicationState],
        config: ParallelSyncConfig | None = None,
    ) -> list[VolumeSyncTask]:
        """Sync multiple volumes in parallel with concurrency control.

        Schedules volume syncs based on priority and respects the
        max_concurrent limit using a semaphore.
        """
        cfg = config or self._parallel

        # Build tasks sorted by priority
        tasks: list[VolumeSyncTask] = []
        for rs in replication_states:
            priority = SyncPriority.NORMAL
            # Boot disks get higher priority
            if rs.resource_name.endswith("-boot"):
                priority = SyncPriority.HIGH
            # Large volumes get critical priority (likely database)
            if rs.data_total_bytes > 500 * 1024 * 1024 * 1024:  # > 500GB
                priority = SyncPriority.CRITICAL

            tasks.append(VolumeSyncTask(
                volume_name=rs.resource_name,
                resource_id=rs.resource_id,
                priority=priority,
                size_gb=round(rs.data_total_bytes / (1024 ** 3), 2),
            ))

        # Sort by priority (CRITICAL first)
        priority_order = {p: i for i, p in enumerate(cfg.priority_order)}
        tasks.sort(key=lambda t: priority_order.get(t.priority, 99))

        # Execute with concurrency limit
        semaphore = asyncio.Semaphore(cfg.max_concurrent)

        async def sync_volume(task: VolumeSyncTask) -> None:
            async with semaphore:
                task.status = "in_progress"
                task.started_at = datetime.now(timezone.utc)

                # Simulate transfer time proportional to size
                await asyncio.sleep(0.01 * max(1, task.size_gb / 100))

                task.transferred_gb = task.size_gb
                task.status = "completed"
                task.completed_at = datetime.now(timezone.utc)

                logger.info(
                    "parallel_sync_volume_completed",
                    volume=task.volume_name,
                    size_gb=task.size_gb,
                    priority=task.priority.value,
                )

        await asyncio.gather(*[sync_volume(t) for t in tasks])

        logger.info(
            "parallel_sync_completed",
            volumes=len(tasks),
            total_gb=round(sum(t.size_gb for t in tasks), 2),
            max_concurrent=cfg.max_concurrent,
        )
        return tasks

    def plan_cutover(
        self,
        replication_states: list[ReplicationState],
        config: CutoverConfig | None = None,
    ) -> CutoverPlan:
        """Plan an optimized cutover to minimize downtime.

        Analyzes current replication state to estimate downtime and
        groups resources for parallel cutover.
        """
        cfg = config or self._cutover

        # Calculate remaining delta
        total_remaining_bytes = sum(
            max(0, rs.data_total_bytes - rs.data_transferred_bytes)
            for rs in replication_states
        )
        remaining_delta_mb = total_remaining_bytes / (1024 * 1024)

        # Estimate downtime: final sync time + verification
        bandwidth_mbps = 1000.0  # 1Gbps assumed
        final_sync_seconds = (remaining_delta_mb * 8) / bandwidth_mbps  # MB → Mb → seconds
        downtime_seconds = final_sync_seconds + cfg.verification_timeout_seconds

        # Pre-staged data
        total_transferred = sum(rs.data_transferred_bytes for rs in replication_states)
        pre_staged_gb = total_transferred / (1024 ** 3)

        # Group resources for parallel cutover
        resource_names = [rs.resource_name for rs in replication_states]

        # Group by type: boot disks together, data volumes together, databases together
        boot_group = [n for n in resource_names if n.endswith("-boot")]
        data_group = [n for n in resource_names if not n.endswith("-boot")]
        parallel_groups = []
        if boot_group:
            parallel_groups.append(boot_group)
        if data_group:
            parallel_groups.append(data_group)

        plan = CutoverPlan(
            estimated_downtime_seconds=round(downtime_seconds, 1),
            pre_staged_gb=round(pre_staged_gb, 2),
            remaining_delta_mb=round(remaining_delta_mb, 2),
            resources_to_cut=resource_names,
            parallel_groups=parallel_groups,
            ready=downtime_seconds <= cfg.max_downtime_seconds,
        )

        logger.info(
            "cutover_planned",
            cutover_id=plan.cutover_id,
            estimated_downtime_seconds=plan.estimated_downtime_seconds,
            max_downtime_seconds=cfg.max_downtime_seconds,
            remaining_delta_mb=plan.remaining_delta_mb,
            ready=plan.ready,
            parallel_groups=len(plan.parallel_groups),
        )
        return plan
