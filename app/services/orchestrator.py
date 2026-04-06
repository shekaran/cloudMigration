"""Sequential migration orchestrator — end-to-end flow with async job execution."""

import asyncio
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, Field

from app.adapters.registry import AdapterRegistry
from app.models.responses import DiscoveredResources
from app.models.vpc import VPCTranslationResult
from app.services.translation import TranslationService
from app.terraform.generator import TerraformGenerator

logger = structlog.get_logger(__name__)


class JobStatus(str, Enum):
    """Migration job lifecycle states."""

    PENDING = "pending"
    DISCOVERING = "discovering"
    NORMALIZING = "normalizing"
    TRANSLATING = "translating"
    GENERATING_TERRAFORM = "generating_terraform"
    MIGRATING_DATA = "migrating_data"
    COMPLETED = "completed"
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


class MigrationOrchestrator:
    """Orchestrates the full migration flow: discover → normalize → translate → terraform → migrate.

    Jobs run asynchronously. Poll status via get_job().
    """

    def __init__(
        self,
        registry: AdapterRegistry,
        translation_service: TranslationService,
        terraform_generator: TerraformGenerator,
        output_base_dir: str | Path = "output",
    ) -> None:
        self._registry = registry
        self._translation = translation_service
        self._terraform = terraform_generator
        self._output_base = Path(output_base_dir)
        self._jobs: dict[UUID, MigrationJob] = {}

    def get_job(self, job_id: UUID) -> MigrationJob | None:
        """Return a job by ID, or None if not found."""
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[MigrationJob]:
        """Return all jobs."""
        return list(self._jobs.values())

    async def execute(self, adapter_name: str) -> MigrationJob:
        """Start a migration job asynchronously.

        Returns the job immediately with PENDING status.
        The actual work runs in the background.
        """
        job = MigrationJob(adapter_name=adapter_name)
        self._jobs[job.job_id] = job

        logger.info("migration_job_created", job_id=str(job.job_id), adapter=adapter_name)

        # Launch the pipeline in the background
        asyncio.create_task(self._run_pipeline(job))

        return job

    async def _run_pipeline(self, job: MigrationJob) -> None:
        """Execute the full migration pipeline sequentially."""
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

            # Step 3: Translate
            job.status = JobStatus.TRANSLATING
            logger.info("pipeline_step", job_id=str(job.job_id), step="translate")

            vpc_result = self._translation.translate(canonical)
            job.steps_completed.append("translate")

            # Step 4: Generate Terraform
            job.status = JobStatus.GENERATING_TERRAFORM
            logger.info("pipeline_step", job_id=str(job.job_id), step="generate_terraform")

            tf_path = self._terraform.generate(vpc_result)
            job.terraform_output = str(tf_path)
            job.steps_completed.append("generate_terraform")

            # Step 5: Mock data migration
            job.status = JobStatus.MIGRATING_DATA
            logger.info("pipeline_step", job_id=str(job.job_id), step="migrate_data")

            migration_dir = await self._mock_data_migration(job, canonical, vpc_result)
            job.migration_output_dir = str(migration_dir)
            job.steps_completed.append("migrate_data")

            # Done
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            logger.info(
                "migration_job_completed",
                job_id=str(job.job_id),
                resource_count=job.resource_count,
                duration_seconds=(job.completed_at - job.started_at).total_seconds(),
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

    async def _mock_data_migration(
        self,
        job: MigrationJob,
        canonical: DiscoveredResources,
        vpc_result: VPCTranslationResult,
    ) -> Path:
        """Simulate rsync-based data migration by writing output files."""
        migration_dir = self._output_base / "migrations" / str(job.job_id)
        migration_dir.mkdir(parents=True, exist_ok=True)

        # Write migration manifest
        manifest = {
            "job_id": str(job.job_id),
            "adapter": job.adapter_name,
            "started_at": job.started_at.isoformat(),
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
        import json

        (migration_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str)
        )

        # Simulate per-VM rsync logs
        for vm in canonical.compute:
            vm_dir = migration_dir / vm.name
            vm_dir.mkdir(exist_ok=True)

            rsync_log = (
                f"# rsync simulation for {vm.name}\n"
                f"# Source: {vm.platform}:{','.join(vm.ip_addresses)}\n"
                f"# OS: {vm.os}\n"
                f"# Storage: {vm.storage_gb}GB boot\n"
                f"\n"
                f"sending incremental file list\n"
                f"  /boot/     {vm.storage_gb * 10}MB\n"
                f"  /var/data/ {vm.storage_gb * 50}MB\n"
                f"\n"
                f"sent {vm.storage_gb * 60}MB  received 1.2KB  avg speed: 125MB/s\n"
                f"total size is {vm.storage_gb * 60}MB  speedup is 1.00\n"
                f"STATUS: COMPLETE\n"
            )
            (vm_dir / "rsync.log").write_text(rsync_log)

            # Write a simulated disk inventory
            disk_inventory = (
                f"# Disk inventory for {vm.name}\n"
                f"boot_disk: {vm.storage_gb}GB\n"
            )
            for vol in canonical.storage:
                if vm.name in vol.name:
                    disk_inventory += f"data_disk: {vol.size_gb}GB ({vol.name})\n"
            (vm_dir / "disk_inventory.txt").write_text(disk_inventory)

        # Simulate a short delay to make async behavior observable
        await asyncio.sleep(0.1)

        logger.info(
            "mock_data_migration_completed",
            job_id=str(job.job_id),
            output_dir=str(migration_dir),
            vms_migrated=len(canonical.compute),
        )
        return migration_dir
