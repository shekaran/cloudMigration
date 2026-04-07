"""Migration API routes — plan, execute, and status endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import (
    get_adapter_registry,
    get_discovery_service,
    get_orchestrator,
    get_translation_service,
)
from app.adapters.registry import AdapterRegistry
from app.core.exceptions import AdapterDiscoveryError, AdapterNotFoundError
from app.models.responses import (
    ErrorResponse,
    JobResponse,
    TranslationResponse,
)
from app.services.discovery import DiscoveryService
from app.services.orchestrator import MigrationOrchestrator
from app.services.translation import TranslationService
from app.terraform.generator import TerraformGenerator

router = APIRouter(tags=["migration"])


@router.post(
    "/plan/{adapter_name}",
    response_model=TranslationResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Adapter not found"},
        500: {"model": ErrorResponse, "description": "Planning failed"},
    },
)
async def plan_migration(
    adapter_name: str,
    discovery_svc: DiscoveryService = Depends(get_discovery_service),
    translation_svc: TranslationService = Depends(get_translation_service),
) -> TranslationResponse:
    """Discover, normalize, translate, and generate Terraform for a source platform.

    Does NOT execute migration — only produces the plan and Terraform output.
    """
    try:
        discovery = await discovery_svc.run(adapter_name)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdapterDiscoveryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        vpc_result = translation_svc.translate(discovery.normalized)
        tf_generator = TerraformGenerator()
        tf_path = tf_generator.generate(vpc_result)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Planning failed: {exc}"
        ) from exc

    return TranslationResponse(
        adapter=adapter_name,
        vpc_name=vpc_result.vpc.name,
        subnets=len(vpc_result.subnets),
        instances=len(vpc_result.instances),
        security_groups=len(vpc_result.security_groups),
        terraform_path=str(tf_path),
    )


@router.post(
    "/execute/{adapter_name}",
    response_model=JobResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Adapter not found"},
    },
)
async def execute_migration(
    adapter_name: str,
    skip_validation: bool = False,
    dry_run: bool = False,
    registry: AdapterRegistry = Depends(get_adapter_registry),
    orchestrator: MigrationOrchestrator = Depends(get_orchestrator),
) -> JobResponse:
    """Start an async migration job for the given adapter.

    Returns immediately with a job_id. Poll GET /status/{job_id} for progress.

    Args:
        skip_validation: If True, validation errors won't block execution.
            All errors will be reported in the job output.
        dry_run: If True, simulate the migration without executing data transfer.
    """
    # Validate adapter exists before creating job
    if adapter_name not in registry.registered_adapters:
        raise HTTPException(status_code=404, detail=f"Adapter not found: '{adapter_name}'")

    job = await orchestrator.execute(adapter_name, skip_validation=skip_validation, dry_run=dry_run)
    return _job_to_response(job)


@router.get(
    "/status/{job_id}",
    response_model=JobResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Job not found"},
    },
)
async def get_job_status(
    job_id: str,
    orchestrator: MigrationOrchestrator = Depends(get_orchestrator),
) -> JobResponse:
    """Poll the status of a migration job."""
    try:
        uid = UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid job_id: {job_id}") from exc

    job = orchestrator.get_job(uid)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return _job_to_response(job)


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(
    orchestrator: MigrationOrchestrator = Depends(get_orchestrator),
) -> list[JobResponse]:
    """List all migration jobs."""
    return [_job_to_response(j) for j in orchestrator.list_jobs()]


@router.post(
    "/resume/{job_id}",
    response_model=JobResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Job not found"},
        400: {"model": ErrorResponse, "description": "Job cannot be resumed"},
    },
)
async def resume_migration(
    job_id: str,
    orchestrator: MigrationOrchestrator = Depends(get_orchestrator),
) -> JobResponse:
    """Resume a failed migration from its last checkpoint.

    Loads the persisted migration plan and continues from the last
    completed stage.
    """
    try:
        uid = UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid job_id: {job_id}") from exc

    job = orchestrator.get_job(uid)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job.status.value not in ("failed", "validation_failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Job cannot be resumed — current status: {job.status.value}",
        )

    # Re-execute (the data migration service will load the persisted plan and resume)
    new_job = await orchestrator.execute(
        job.adapter_name,
        skip_validation=job.skip_validation,
        dry_run=job.dry_run,
    )
    return _job_to_response(new_job)


def _job_to_response(job) -> JobResponse:
    """Convert a MigrationJob to its API response model."""
    return JobResponse(
        job_id=str(job.job_id),
        adapter=job.adapter_name,
        status=job.status.value,
        started_at=job.started_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        error=job.error,
        resource_count=job.resource_count,
        terraform_output=job.terraform_output,
        migration_output_dir=job.migration_output_dir,
        steps_completed=job.steps_completed,
        validation_errors=job.validation_errors,
        validation_warnings=job.validation_warnings,
        strategy_summary=job.strategy_summary,
        firewall_conflicts=job.firewall_conflicts,
        firewall_rules_consolidated=job.firewall_rules_consolidated,
        tier_summary=job.tier_summary,
        k8s_backup_id=job.k8s_backup_id,
        k8s_workloads_migrated=job.k8s_workloads_migrated,
        k8s_target_platform=job.k8s_target_platform,
        containerization_candidates=job.containerization_candidates,
        data_migration_plan_id=job.data_migration_plan_id,
        data_sync_mode=job.data_sync_mode,
        data_total_gb=job.data_total_gb,
        data_delta_gb=job.data_delta_gb,
        db_replications=job.db_replications,
        migration_hooks_executed=job.migration_hooks_executed,
        rollback_checkpoints=job.rollback_checkpoints,
        dry_run=job.dry_run,
        checksums_verified=job.checksums_verified,
        checksums_passed=job.checksums_passed,
        replication_converged=job.replication_converged,
        continuous_sync_iterations=job.continuous_sync_iterations,
        parallel_volumes_synced=job.parallel_volumes_synced,
        estimated_downtime_seconds=job.estimated_downtime_seconds,
        cutover_ready=job.cutover_ready,
    )
