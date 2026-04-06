"""Strategy engine — classifies workloads and assigns migration strategies."""

from enum import Enum

import structlog
from pydantic import BaseModel, Field

from app.graph.engine import DependencyGraph
from app.models.canonical import ComputeResource, ComputeType, StorageVolume
from app.models.responses import DiscoveredResources

logger = structlog.get_logger(__name__)


class MigrationStrategy(str, Enum):
    """Available migration strategies."""

    LIFT_AND_SHIFT = "lift_and_shift"
    REPLATFORM = "replatform"
    REBUILD = "rebuild"
    KUBERNETES_MIGRATION = "kubernetes_migration"


class StrategyRationale(BaseModel):
    """Explains why a particular strategy was chosen for a resource."""

    resource_name: str = Field(description="Name of the resource")
    resource_id: str = Field(description="UUID of the resource")
    resource_type: str = Field(description="Type of resource (compute, network, etc.)")
    strategy: MigrationStrategy = Field(description="Assigned migration strategy")
    reasons: list[str] = Field(default_factory=list, description="Why this strategy was chosen")
    risk_level: str = Field(default="low", description="low, medium, or high")
    estimated_downtime: str = Field(default="minimal", description="Estimated downtime category")


class StrategyResult(BaseModel):
    """Complete strategy analysis for a set of discovered resources."""

    assignments: dict[str, MigrationStrategy] = Field(
        default_factory=dict,
        description="Resource UUID → assigned strategy",
    )
    rationales: list[StrategyRationale] = Field(
        default_factory=list,
        description="Detailed rationale for each assignment",
    )
    summary: dict[str, int] = Field(
        default_factory=dict,
        description="Strategy → count of resources assigned",
    )


# Classification thresholds
_HIGH_CPU_THRESHOLD = 16
_HIGH_MEMORY_THRESHOLD = 64
_LARGE_STORAGE_THRESHOLD = 500  # GB


class StrategyEngine:
    """Classifies workloads and assigns migration strategies.

    Strategy selection is based on:
    - Resource type (VM, container, baremetal)
    - Statefulness (stateful workloads get more conservative strategies)
    - Resource sizing (large workloads may need replatforming)
    - Dependencies (heavily depended-on resources are higher risk)
    - Platform (some platforms require specific strategies)
    """

    def analyze(
        self,
        resources: DiscoveredResources,
        graph: DependencyGraph,
    ) -> StrategyResult:
        """Analyze resources and assign migration strategies.

        Args:
            resources: Discovered canonical resources.
            graph: Dependency graph for relationship analysis.

        Returns:
            StrategyResult with per-resource strategy assignments and rationales.
        """
        logger.info("strategy_analysis_started", resource_count=resources.resource_count)

        assignments: dict[str, MigrationStrategy] = {}
        rationales: list[StrategyRationale] = []

        for vm in resources.compute:
            strategy, rationale = self._classify_compute(vm, graph)
            assignments[str(vm.id)] = strategy
            rationales.append(rationale)

        # Storage inherits strategy from its attached compute
        compute_strategies = {str(vm.id): assignments.get(str(vm.id)) for vm in resources.compute}
        for vol in resources.storage:
            strategy, rationale = self._classify_storage(vol, compute_strategies)
            assignments[str(vol.id)] = strategy
            rationales.append(rationale)

        # Networks and security policies are always lift-and-shift (infrastructure)
        for net in resources.networks:
            strategy = MigrationStrategy.LIFT_AND_SHIFT
            assignments[str(net.id)] = strategy
            rationales.append(StrategyRationale(
                resource_name=net.name,
                resource_id=str(net.id),
                resource_type="network",
                strategy=strategy,
                reasons=["Network infrastructure is always migrated as-is"],
                risk_level="low",
                estimated_downtime="minimal",
            ))

        for sp in resources.security_policies:
            strategy = MigrationStrategy.LIFT_AND_SHIFT
            assignments[str(sp.id)] = strategy
            rationales.append(StrategyRationale(
                resource_name=sp.name,
                resource_id=str(sp.id),
                resource_type="security_policy",
                strategy=strategy,
                reasons=["Security policies are translated to VPC security groups"],
                risk_level="low",
                estimated_downtime="none",
            ))

        # Build summary
        summary: dict[str, int] = {}
        for strategy in assignments.values():
            summary[strategy.value] = summary.get(strategy.value, 0) + 1

        result = StrategyResult(
            assignments=assignments,
            rationales=rationales,
            summary=summary,
        )

        logger.info(
            "strategy_analysis_completed",
            total_resources=len(assignments),
            summary=summary,
        )
        return result

    def _classify_compute(
        self,
        vm: ComputeResource,
        graph: DependencyGraph,
    ) -> tuple[MigrationStrategy, StrategyRationale]:
        """Classify a compute resource into a migration strategy."""
        reasons: list[str] = []
        risk = "low"
        downtime = "minimal"

        # Container workloads → kubernetes_migration
        if vm.type == ComputeType.CONTAINER:
            strategy = MigrationStrategy.KUBERNETES_MIGRATION
            reasons.append("Container workload requires Kubernetes migration")
            return strategy, StrategyRationale(
                resource_name=vm.name,
                resource_id=str(vm.id),
                resource_type="compute",
                strategy=strategy,
                reasons=reasons,
                risk_level="medium",
                estimated_downtime="moderate",
            )

        # Bare metal → rebuild
        if vm.type == ComputeType.BAREMETAL:
            strategy = MigrationStrategy.REBUILD
            reasons.append("Bare metal workload requires rebuild on VPC")
            return strategy, StrategyRationale(
                resource_name=vm.name,
                resource_id=str(vm.id),
                resource_type="compute",
                strategy=strategy,
                reasons=reasons,
                risk_level="high",
                estimated_downtime="extended",
            )

        # VM classification based on characteristics
        score = 0  # higher score → more complex → replatform

        # Statefulness
        if vm.stateful:
            score += 2
            reasons.append("Stateful workload (database/data tier)")
            risk = "medium"
            downtime = "moderate"

        # Resource sizing
        if vm.cpu >= _HIGH_CPU_THRESHOLD or vm.memory_gb >= _HIGH_MEMORY_THRESHOLD:
            score += 1
            reasons.append(f"High resource sizing ({vm.cpu} CPU, {vm.memory_gb}GB RAM)")

        # Large storage
        if vm.storage_gb >= _LARGE_STORAGE_THRESHOLD:
            score += 1
            reasons.append(f"Large root disk ({vm.storage_gb}GB)")
            downtime = "moderate"

        # Dependency count — heavily depended-on resources are higher risk
        dependents = graph.dependents_of(vm.id)
        if len(dependents) >= 3:
            score += 1
            reasons.append(f"Critical resource — {len(dependents)} resources depend on it")
            risk = "high"

        # OS-based heuristics
        os_lower = vm.os.lower()
        if any(legacy in os_lower for legacy in ("windows", "sles", "aix")):
            score += 2
            reasons.append(f"Legacy/complex OS ({vm.os}) may require replatforming")
            risk = "medium"

        # Decide strategy
        if score >= 3:
            strategy = MigrationStrategy.REPLATFORM
            if not reasons:
                reasons.append("Complex workload characteristics require replatforming")
        else:
            strategy = MigrationStrategy.LIFT_AND_SHIFT
            if not reasons:
                reasons.append("Standard VM suitable for lift-and-shift migration")

        return strategy, StrategyRationale(
            resource_name=vm.name,
            resource_id=str(vm.id),
            resource_type="compute",
            strategy=strategy,
            reasons=reasons,
            risk_level=risk,
            estimated_downtime=downtime,
        )

    def _classify_storage(
        self,
        vol: StorageVolume,
        compute_strategies: dict[str, MigrationStrategy | None],
    ) -> tuple[MigrationStrategy, StrategyRationale]:
        """Storage inherits the strategy of its attached compute resource."""
        reasons: list[str] = []

        if vol.attached_to:
            parent_strategy = compute_strategies.get(str(vol.attached_to))
            if parent_strategy:
                reasons.append(f"Inherits strategy from attached compute resource")
                return parent_strategy, StrategyRationale(
                    resource_name=vol.name,
                    resource_id=str(vol.id),
                    resource_type="storage",
                    strategy=parent_strategy,
                    reasons=reasons,
                    risk_level="low",
                    estimated_downtime="minimal",
                )

        # Unattached or unknown — default to lift-and-shift
        strategy = MigrationStrategy.LIFT_AND_SHIFT
        reasons.append("Standalone storage volume — lift-and-shift")
        return strategy, StrategyRationale(
            resource_name=vol.name,
            resource_id=str(vol.id),
            resource_type="storage",
            strategy=strategy,
            reasons=reasons,
            risk_level="low",
            estimated_downtime="minimal",
        )
