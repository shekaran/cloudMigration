"""Temporal workflow — orchestrates the full migration pipeline with retry and state tracking."""

from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.workflows.activities import (
        AnalyzeInput,
        AnalyzeOutput,
        DiscoverInput,
        DiscoverOutput,
        MigrateInput,
        MigrateOutput,
        NormalizeInput,
        NormalizeOutput,
        TranslateInput,
        TranslateOutput,
        ValidateInput,
        ValidateOutput,
    )

# Default retry policy for all activities
_DEFAULT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
)


@dataclass
class MigrationWorkflowInput:
    """Input to the migration workflow."""

    adapter_name: str
    job_id: str
    skip_validation: bool = False


@dataclass
class MigrationWorkflowOutput:
    """Output from the migration workflow."""

    job_id: str
    adapter_name: str
    status: str = "completed"
    resource_count: int = 0
    terraform_path: str = ""
    migration_dir: str = ""
    graph_dot: str = ""
    strategy_summary: str = ""
    network_plan_summary: str = ""
    validation_summary: str = ""
    steps_completed: list[str] = field(default_factory=list)
    error: str | None = None


@workflow.defn
class MigrationWorkflow:
    """Temporal workflow that orchestrates the full migration pipeline.

    Steps:
        1. Discover — fetch raw data from source platform
        2. Normalize — convert to canonical model
        3. Validate — pre-migration checks (blocks by default)
        4. Analyze — dependency graph, strategy classification, network planning
        5. Translate — convert to VPC model + generate Terraform
        6. Migrate — mock data migration

    Each step is a Temporal activity with retry policy.
    The workflow maintains state for status queries.
    """

    def __init__(self) -> None:
        self._current_step = "pending"
        self._steps_completed: list[str] = []

    @workflow.run
    async def run(self, input: MigrationWorkflowInput) -> MigrationWorkflowOutput:
        """Execute the full migration pipeline."""
        output = MigrationWorkflowOutput(
            job_id=input.job_id,
            adapter_name=input.adapter_name,
        )

        try:
            # Step 1: Discover
            self._current_step = "discovering"
            discover_result: DiscoverOutput = await workflow.execute_activity(
                "discover",
                DiscoverInput(adapter_name=input.adapter_name),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_DEFAULT_RETRY,
            )
            self._steps_completed.append("discover")

            # Step 2: Normalize
            self._current_step = "normalizing"
            normalize_result: NormalizeOutput = await workflow.execute_activity(
                "normalize",
                NormalizeInput(
                    adapter_name=input.adapter_name,
                    raw_data=discover_result.raw_data,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_DEFAULT_RETRY,
            )
            output.resource_count = normalize_result.resource_count
            self._steps_completed.append("normalize")

            # Step 3: Validate
            self._current_step = "validating"
            validate_result: ValidateOutput = await workflow.execute_activity(
                "validate",
                ValidateInput(
                    canonical_json=normalize_result.canonical_json,
                    skip_validation=input.skip_validation,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_DEFAULT_RETRY,
            )
            output.validation_summary = (
                f"errors={validate_result.error_count}, "
                f"warnings={validate_result.warning_count}"
            )
            self._steps_completed.append("validate")

            if not validate_result.passed:
                output.status = "validation_failed"
                output.error = (
                    f"Validation failed with {validate_result.error_count} errors. "
                    f"Re-run with skip_validation=true to override."
                )
                output.steps_completed = list(self._steps_completed)
                return output

            # Step 4: Analyze (graph + strategy + network plan)
            self._current_step = "analyzing"
            analyze_result: AnalyzeOutput = await workflow.execute_activity(
                "analyze",
                AnalyzeInput(canonical_json=normalize_result.canonical_json),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_DEFAULT_RETRY,
            )
            output.graph_dot = analyze_result.graph_dot
            output.strategy_summary = analyze_result.strategy_json[:200]
            output.network_plan_summary = analyze_result.network_plan_json[:200]
            self._steps_completed.append("analyze")

            # Step 5: Translate + Generate Terraform
            self._current_step = "translating"
            translate_result: TranslateOutput = await workflow.execute_activity(
                "translate",
                TranslateInput(
                    canonical_json=normalize_result.canonical_json,
                    strategy_json=analyze_result.strategy_json,
                    network_plan_json=analyze_result.network_plan_json,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=_DEFAULT_RETRY,
            )
            output.terraform_path = translate_result.terraform_path
            self._steps_completed.append("translate")

            # Step 6: Migrate data
            self._current_step = "migrating"
            migrate_result: MigrateOutput = await workflow.execute_activity(
                "migrate_data",
                MigrateInput(
                    canonical_json=normalize_result.canonical_json,
                    vpc_result_json=translate_result.vpc_result_json,
                    job_id=input.job_id,
                    adapter_name=input.adapter_name,
                ),
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=_DEFAULT_RETRY,
            )
            output.migration_dir = migrate_result.migration_dir
            self._steps_completed.append("migrate_data")

            output.status = "completed"
            output.steps_completed = list(self._steps_completed)

        except Exception as e:
            output.status = "failed"
            output.error = str(e)
            output.steps_completed = list(self._steps_completed)

        return output

    @workflow.query
    def current_step(self) -> str:
        """Query the current step of the workflow."""
        return self._current_step

    @workflow.query
    def steps_completed(self) -> list[str]:
        """Query the list of completed steps."""
        return list(self._steps_completed)
