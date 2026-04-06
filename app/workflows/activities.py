"""Temporal activities — individual steps in the migration workflow."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


@dataclass
class DiscoverInput:
    adapter_name: str


@dataclass
class DiscoverOutput:
    raw_data: dict[str, Any]
    adapter_name: str


@dataclass
class NormalizeInput:
    adapter_name: str
    raw_data: dict[str, Any]


@dataclass
class NormalizeOutput:
    canonical_json: str  # JSON-serialized DiscoveredResources
    resource_count: int


@dataclass
class ValidateInput:
    canonical_json: str
    skip_validation: bool = False


@dataclass
class ValidateOutput:
    passed: bool
    validation_json: str  # JSON-serialized ValidationResult
    error_count: int
    warning_count: int


@dataclass
class AnalyzeInput:
    canonical_json: str


@dataclass
class AnalyzeOutput:
    graph_json: str  # JSON-serialized graph dict
    graph_dot: str  # Graphviz DOT string
    strategy_json: str  # JSON-serialized StrategyResult
    network_plan_json: str  # JSON-serialized NetworkPlan
    execution_order: list[str]  # UUIDs in topological order


@dataclass
class TranslateInput:
    canonical_json: str
    strategy_json: str
    network_plan_json: str


@dataclass
class TranslateOutput:
    vpc_result_json: str  # JSON-serialized VPCTranslationResult
    terraform_path: str


@dataclass
class MigrateInput:
    canonical_json: str
    vpc_result_json: str
    job_id: str
    adapter_name: str


@dataclass
class MigrateOutput:
    migration_dir: str
    vms_migrated: int


class MigrationActivities:
    """Temporal activity implementations backed by existing services.

    Activities are stateless — they receive all inputs and use
    injected services to do the work.
    """

    def __init__(
        self,
        registry,
        translation_service,
        terraform_generator,
        strategy_engine,
        validation_engine,
        network_planner,
        output_base_dir: str = "output",
    ) -> None:
        self._registry = registry
        self._translation = translation_service
        self._terraform = terraform_generator
        self._strategy = strategy_engine
        self._validation = validation_engine
        self._network_planner = network_planner
        self._output_base = Path(output_base_dir)

    @activity.defn
    async def discover(self, input: DiscoverInput) -> DiscoverOutput:
        """Activity: Discover resources from source platform."""
        logger.info("activity_discover", adapter=input.adapter_name)
        adapter = self._registry.get_adapter(input.adapter_name)
        raw_data = await adapter.discover()
        return DiscoverOutput(raw_data=raw_data, adapter_name=input.adapter_name)

    @activity.defn
    async def normalize(self, input: NormalizeInput) -> NormalizeOutput:
        """Activity: Normalize raw data into canonical model."""
        logger.info("activity_normalize", adapter=input.adapter_name)
        adapter = self._registry.get_adapter(input.adapter_name)
        canonical = adapter.normalize(input.raw_data)
        return NormalizeOutput(
            canonical_json=canonical.model_dump_json(),
            resource_count=canonical.resource_count,
        )

    @activity.defn
    async def validate(self, input: ValidateInput) -> ValidateOutput:
        """Activity: Run pre-migration validation checks."""
        from app.graph.engine import build_graph
        from app.models.responses import DiscoveredResources

        logger.info("activity_validate")
        canonical = DiscoveredResources.model_validate_json(input.canonical_json)
        graph = build_graph(canonical)
        result = self._validation.validate(canonical, graph)

        return ValidateOutput(
            passed=result.passed or input.skip_validation,
            validation_json=result.model_dump_json(),
            error_count=result.error_count,
            warning_count=result.warning_count,
        )

    @activity.defn
    async def analyze(self, input: AnalyzeInput) -> AnalyzeOutput:
        """Activity: Build dependency graph, run strategy analysis, plan network."""
        from app.graph.engine import build_graph
        from app.models.responses import DiscoveredResources

        logger.info("activity_analyze")
        canonical = DiscoveredResources.model_validate_json(input.canonical_json)
        graph = build_graph(canonical)

        # Strategy analysis
        strategy_result = self._strategy.analyze(canonical, graph)

        # Network planning
        network_plan = self._network_planner.plan(canonical.networks)

        # Execution order
        order = graph.topological_sort()

        return AnalyzeOutput(
            graph_json=json.dumps(graph.to_dict(), default=str),
            graph_dot=graph.to_dot(),
            strategy_json=strategy_result.model_dump_json(),
            network_plan_json=network_plan.model_dump_json(),
            execution_order=[str(uid) for uid in order],
        )

    @activity.defn
    async def translate(self, input: TranslateInput) -> TranslateOutput:
        """Activity: Translate canonical model to VPC and generate Terraform."""
        from app.models.responses import DiscoveredResources
        from app.services.network_planner import NetworkPlan
        from app.services.strategy import StrategyResult

        logger.info("activity_translate")
        canonical = DiscoveredResources.model_validate_json(input.canonical_json)
        strategy_result = StrategyResult.model_validate_json(input.strategy_json)
        network_plan = NetworkPlan.model_validate_json(input.network_plan_json)

        vpc_result = self._translation.translate(
            canonical,
            strategy_result=strategy_result,
            network_plan=network_plan,
        )
        tf_path = self._terraform.generate(vpc_result)

        return TranslateOutput(
            vpc_result_json=vpc_result.model_dump_json(),
            terraform_path=str(tf_path),
        )

    @activity.defn
    async def migrate_data(self, input: MigrateInput) -> MigrateOutput:
        """Activity: Perform mock data migration."""
        import asyncio
        from app.models.responses import DiscoveredResources
        from app.models.vpc import VPCTranslationResult

        logger.info("activity_migrate_data", job_id=input.job_id)
        canonical = DiscoveredResources.model_validate_json(input.canonical_json)
        vpc_result = VPCTranslationResult.model_validate_json(input.vpc_result_json)

        migration_dir = self._output_base / "migrations" / input.job_id
        migration_dir.mkdir(parents=True, exist_ok=True)

        # Write manifest
        manifest = {
            "job_id": input.job_id,
            "adapter": input.adapter_name,
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

        # Per-VM rsync logs
        for vm in canonical.compute:
            vm_dir = migration_dir / vm.name
            vm_dir.mkdir(exist_ok=True)
            rsync_log = (
                f"# rsync simulation for {vm.name}\n"
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

        await asyncio.sleep(0.1)

        return MigrateOutput(
            migration_dir=str(migration_dir),
            vms_migrated=len(canonical.compute),
        )
