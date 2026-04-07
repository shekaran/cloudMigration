"""Migration orchestrator — end-to-end flow with Phase 2 engines (graph, strategy, validation, network)."""

import asyncio
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, Field

from app.adapters.registry import AdapterRegistry
from app.graph.engine import build_graph
from app.models.responses import DiscoveredResources
from app.models.vpc import VPCTranslationResult
from app.services.containerization import ContainerizationRecommender
from app.services.firewall_engine import FirewallEngine
from app.services.k8s_migration import K8sMigrationService
from app.services.k8s_translation import K8sTranslationService
from app.services.network_planner import NetworkPlanner
from app.services.strategy import StrategyEngine
from app.services.translation import TranslationService
from app.services.validation import ValidationEngine
from app.terraform.generator import TerraformGenerator

logger = structlog.get_logger(__name__)


class JobStatus(str, Enum):
    """Migration job lifecycle states."""

    PENDING = "pending"
    DISCOVERING = "discovering"
    NORMALIZING = "normalizing"
    VALIDATING = "validating"
    ANALYZING = "analyzing"
    TRANSLATING = "translating"
    GENERATING_TERRAFORM = "generating_terraform"
    MIGRATING_DATA = "migrating_data"
    COMPLETED = "completed"
    VALIDATION_FAILED = "validation_failed"
    FAILED = "failed"


class MigrationJob(BaseModel):
    """Tracks the state and output of a migration execution."""

    job_id: UUID = Field(default_factory=uuid4)
    adapter_name: str
    status: JobStatus = JobStatus.PENDING
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error: str | None = None
    resource_count: int = 0
    terraform_output: str | None = None
    migration_output_dir: str | None = None
    steps_completed: list[str] = Field(default_factory=list)
    skip_validation: bool = False
    validation_errors: int = 0
    validation_warnings: int = 0
    strategy_summary: dict[str, int] = Field(default_factory=dict)
    graph_dot: str | None = None
    firewall_conflicts: int = 0
    firewall_rules_consolidated: int = 0
    tier_summary: dict[str, int] = Field(default_factory=dict)
    k8s_backup_id: str | None = None
    k8s_workloads_migrated: int = 0
    k8s_target_platform: str | None = None
    containerization_candidates: int = 0


class MigrationOrchestrator:
    """Orchestrates the full migration flow.

    VM Pipeline: discover → normalize → validate → analyze → translate → terraform → migrate.
    K8s Pipeline: discover → normalize → validate → backup → translate → restore.
    Jobs run asynchronously. Poll status via get_job().
    """

    def __init__(
        self,
        registry: AdapterRegistry,
        translation_service: TranslationService,
        terraform_generator: TerraformGenerator,
        strategy_engine: StrategyEngine | None = None,
        validation_engine: ValidationEngine | None = None,
        network_planner: NetworkPlanner | None = None,
        firewall_engine: FirewallEngine | None = None,
        k8s_translation_service: K8sTranslationService | None = None,
        k8s_migration_service: K8sMigrationService | None = None,
        containerization_recommender: ContainerizationRecommender | None = None,
        output_base_dir: str | Path = "output",
    ) -> None:
        self._registry = registry
        self._translation = translation_service
        self._terraform = terraform_generator
        self._strategy = strategy_engine or StrategyEngine()
        self._validation = validation_engine or ValidationEngine()
        self._network_planner = network_planner or NetworkPlanner()
        self._firewall = firewall_engine or FirewallEngine()
        self._k8s_translation = k8s_translation_service
        self._k8s_migration = k8s_migration_service
        self._containerization = containerization_recommender
        self._output_base = Path(output_base_dir)
        self._jobs: dict[UUID, MigrationJob] = {}

    def get_job(self, job_id: UUID) -> MigrationJob | None:
        """Return a job by ID, or None if not found."""
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[MigrationJob]:
        """Return all jobs."""
        return list(self._jobs.values())

    async def execute(self, adapter_name: str, skip_validation: bool = False) -> MigrationJob:
        """Start a migration job asynchronously.

        Args:
            adapter_name: Source platform adapter name.
            skip_validation: If True, validation errors won't block execution.

        Returns the job immediately with PENDING status.
        """
        job = MigrationJob(adapter_name=adapter_name, skip_validation=skip_validation)
        self._jobs[job.job_id] = job

        logger.info(
            "migration_job_created",
            job_id=str(job.job_id),
            adapter=adapter_name,
            skip_validation=skip_validation,
        )

        asyncio.create_task(self._run_pipeline(job))
        return job

    async def _run_pipeline(self, job: MigrationJob) -> None:
        """Execute the migration pipeline — routes to K8s or VM pipeline based on adapter."""
        try:
            # Step 1: Discover
            job.status = JobStatus.DISCOVERING
            logger.info("pipeline_step", job_id=str(job.job_id), step="discover")
            adapter = self._registry.get_adapter(job.adapter_name)
            raw_data = await adapter.discover()
            job.steps_completed.append("discover")

            # Step 2: Normalize
            job.status = JobStatus.NORMALIZING
            logger.info("pipeline_step", job_id=str(job.job_id), step="normalize")
            canonical = adapter.normalize(raw_data)
            job.resource_count = canonical.resource_count
            job.steps_completed.append("normalize")

            # Step 3: Validate
            job.status = JobStatus.VALIDATING
            logger.info("pipeline_step", job_id=str(job.job_id), step="validate")
            graph = build_graph(canonical)
            validation_result = self._validation.validate(canonical, graph)
            job.validation_errors = validation_result.error_count
            job.validation_warnings = validation_result.warning_count
            job.steps_completed.append("validate")

            if not validation_result.passed and not job.skip_validation:
                job.status = JobStatus.VALIDATION_FAILED
                job.error = (
                    f"Validation failed with {validation_result.error_count} errors, "
                    f"{validation_result.warning_count} warnings. "
                    f"Re-run with skip_validation=true to override."
                )
                job.completed_at = datetime.now(timezone.utc)
                logger.warning(
                    "migration_validation_failed",
                    job_id=str(job.job_id),
                    errors=validation_result.error_count,
                )
                return

            # Route to K8s or VM pipeline
            if canonical.kubernetes and self._k8s_translation and self._k8s_migration:
                await self._run_k8s_pipeline(job, canonical, graph)
            else:
                await self._run_vm_pipeline(job, canonical, graph)

            # Containerization recommendations (for VM adapters)
            if canonical.compute and self._containerization:
                container_result = self._containerization.analyze(canonical)
                job.containerization_candidates = container_result.total_candidates

            # Done
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            logger.info(
                "migration_job_completed",
                job_id=str(job.job_id),
                resource_count=job.resource_count,
                duration_seconds=(job.completed_at - job.started_at).total_seconds(),
                strategies=job.strategy_summary,
            )

        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            logger.error(
                "migration_job_failed",
                job_id=str(job.job_id),
                step=job.status.value,
                error=str(exc),
            )

    async def _run_vm_pipeline(
        self,
        job: MigrationJob,
        canonical: DiscoveredResources,
        graph,
    ) -> None:
        """VM migration pipeline: analyze → translate → terraform → migrate."""
        # Step 4: Analyze (graph + strategy + firewall + network plan)
        job.status = JobStatus.ANALYZING
        logger.info("pipeline_step", job_id=str(job.job_id), step="analyze")
        strategy_result = self._strategy.analyze(canonical, graph)
        firewall_result = self._firewall.analyze(canonical)
        network_plan = self._network_planner.plan(canonical.networks, canonical.compute)
        job.strategy_summary = strategy_result.summary
        job.graph_dot = graph.to_dot()
        job.firewall_conflicts = len(firewall_result.conflicts)
        job.firewall_rules_consolidated = firewall_result.consolidated_count
        job.tier_summary = {
            t.tier: t.subnet_count for t in network_plan.tier_allocations
        }

        execution_order = graph.topological_sort()
        stages = graph.parallel_stages()
        logger.info(
            "pipeline_analysis",
            job_id=str(job.job_id),
            strategies=strategy_result.summary,
            subnets_planned=len(network_plan.allocations),
            execution_stages=len(stages),
            firewall_conflicts=len(firewall_result.conflicts),
            tiers=list(job.tier_summary.keys()),
        )
        job.steps_completed.append("analyze")

        # Step 5: Translate (strategy-aware + network-planned)
        job.status = JobStatus.TRANSLATING
        logger.info("pipeline_step", job_id=str(job.job_id), step="translate")
        vpc_result = self._translation.translate(
            canonical,
            strategy_result=strategy_result,
            network_plan=network_plan,
        )
        job.steps_completed.append("translate")

        # Step 6: Generate Terraform
        job.status = JobStatus.GENERATING_TERRAFORM
        logger.info("pipeline_step", job_id=str(job.job_id), step="generate_terraform")
        tf_path = self._terraform.generate(vpc_result)
        job.terraform_output = str(tf_path)
        job.steps_completed.append("generate_terraform")

        # Step 7: Mock data migration
        job.status = JobStatus.MIGRATING_DATA
        logger.info("pipeline_step", job_id=str(job.job_id), step="migrate_data")
        migration_dir = await self._mock_data_migration(
            job, canonical, vpc_result, strategy_result
        )
        job.migration_output_dir = str(migration_dir)
        job.steps_completed.append("migrate_data")

    async def _run_k8s_pipeline(
        self,
        job: MigrationJob,
        canonical: DiscoveredResources,
        graph,
    ) -> None:
        """K8s migration pipeline: analyze → backup → translate → restore → validate."""
        assert self._k8s_translation is not None
        assert self._k8s_migration is not None

        # Step 4: Analyze
        job.status = JobStatus.ANALYZING
        logger.info("pipeline_step", job_id=str(job.job_id), step="analyze")
        strategy_result = self._strategy.analyze(canonical, graph)
        job.strategy_summary = strategy_result.summary
        job.graph_dot = graph.to_dot()
        job.steps_completed.append("analyze")

        # Step 5: Backup
        logger.info("pipeline_step", job_id=str(job.job_id), step="k8s_backup")
        backup = self._k8s_migration.backup(canonical)
        job.k8s_backup_id = backup.backup_id
        job.steps_completed.append("k8s_backup")

        # Step 6: Translate (K8s → IKS/OpenShift)
        job.status = JobStatus.TRANSLATING
        logger.info("pipeline_step", job_id=str(job.job_id), step="k8s_translate")
        k8s_result = self._k8s_translation.translate(canonical)
        job.k8s_workloads_migrated = len(k8s_result.workloads)
        job.k8s_target_platform = k8s_result.cluster.platform.value
        job.steps_completed.append("k8s_translate")

        # Step 7: Restore
        job.status = JobStatus.MIGRATING_DATA
        logger.info("pipeline_step", job_id=str(job.job_id), step="k8s_restore")
        restore_dir = self._k8s_migration.restore(backup, k8s_result)
        job.migration_output_dir = str(restore_dir)
        job.steps_completed.append("k8s_restore")

        # Step 8: Validate restore
        logger.info("pipeline_step", job_id=str(job.job_id), step="k8s_validate_restore")
        validation = self._k8s_migration.validate(backup, k8s_result)
        if not validation.passed:
            logger.warning(
                "k8s_restore_validation_issues",
                job_id=str(job.job_id),
                failed_checks=validation.failed_checks,
                warnings=validation.warnings,
            )
        job.steps_completed.append("k8s_validate_restore")

        await asyncio.sleep(0.1)

    async def _mock_data_migration(
        self,
        job: MigrationJob,
        canonical: DiscoveredResources,
        vpc_result: VPCTranslationResult,
        strategy_result=None,
    ) -> Path:
        """Simulate rsync-based data migration by writing output files."""
        migration_dir = self._output_base / "migrations" / str(job.job_id)
        migration_dir.mkdir(parents=True, exist_ok=True)

        # Strategy lookup
        strategies = {}
        if strategy_result:
            strategies = strategy_result.assignments

        manifest = {
            "job_id": str(job.job_id),
            "adapter": job.adapter_name,
            "started_at": job.started_at.isoformat(),
            "skip_validation": job.skip_validation,
            "validation_errors": job.validation_errors,
            "validation_warnings": job.validation_warnings,
            "strategy_summary": job.strategy_summary,
            "firewall_conflicts": job.firewall_conflicts,
            "firewall_rules_consolidated": job.firewall_rules_consolidated,
            "tier_summary": job.tier_summary,
            "source_resources": {
                "compute": len(canonical.compute),
                "networks": len(canonical.networks),
                "security_policies": len(canonical.security_policies),
                "storage": len(canonical.storage),
            },
            "target_resources": {
                "vpc": vpc_result.vpc.name,
                "subnets": [s.name for s in vpc_result.subnets],
                "instances": [i.name for i in vpc_result.instances],
                "security_groups": [sg.name for sg in vpc_result.security_groups],
            },
        }
        (migration_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str)
        )

        for vm in canonical.compute:
            vm_dir = migration_dir / vm.name
            vm_dir.mkdir(exist_ok=True)

            vm_strategy = strategies.get(str(vm.id), "lift_and_shift")
            if hasattr(vm_strategy, 'value'):
                vm_strategy = vm_strategy.value

            rsync_log = (
                f"# rsync simulation for {vm.name}\n"
                f"# Strategy: {vm_strategy}\n"
                f"# Source: {vm.platform}:{','.join(vm.ip_addresses)}\n"
                f"# OS: {vm.os}\n"
                f"# Storage: {vm.storage_gb}GB boot\n\n"
                f"sending incremental file list\n"
                f"  /boot/     {vm.storage_gb * 10}MB\n"
                f"  /var/data/ {vm.storage_gb * 50}MB\n\n"
                f"sent {vm.storage_gb * 60}MB  received 1.2KB  avg speed: 125MB/s\n"
                f"STATUS: COMPLETE\n"
            )
            (vm_dir / "rsync.log").write_text(rsync_log)

            disk_inventory = (
                f"# Disk inventory for {vm.name}\n"
                f"strategy: {vm_strategy}\n"
                f"boot_disk: {vm.storage_gb}GB\n"
            )
            for vol in canonical.storage:
                if vm.name in vol.name:
                    disk_inventory += f"data_disk: {vol.size_gb}GB ({vol.name})\n"
            (vm_dir / "disk_inventory.txt").write_text(disk_inventory)

        await asyncio.sleep(0.1)

        logger.info(
            "mock_data_migration_completed",
            job_id=str(job.job_id),
            output_dir=str(migration_dir),
            vms_migrated=len(canonical.compute),
        )
        return migration_dir
