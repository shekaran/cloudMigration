"""Containerization recommender — analyzes VMs and recommends containerization candidates.

Evaluates compute resources against containerization criteria and produces
advisory recommendations for VM-to-container modernization.
"""

from __future__ import annotations

from enum import Enum

import structlog
from pydantic import BaseModel, Field

from app.models.canonical import ComputeResource, ComputeType
from app.models.responses import DiscoveredResources

logger = structlog.get_logger(__name__)


class ContainerizationFitness(str, Enum):
    """How suitable a VM is for containerization."""

    EXCELLENT = "excellent"
    GOOD = "good"
    POSSIBLE = "possible"
    NOT_RECOMMENDED = "not_recommended"


class ContainerizationRecommendation(BaseModel):
    """Advisory recommendation for containerizing a VM."""

    resource_name: str = Field(description="VM name")
    resource_id: str = Field(description="VM UUID")
    fitness: ContainerizationFitness = Field(description="Containerization suitability")
    score: int = Field(description="Fitness score (0-100)")
    reasons: list[str] = Field(default_factory=list, description="Why this fitness level")
    suggested_approach: str = Field(
        default="", description="Recommended containerization approach"
    )
    target_workload_type: str = Field(
        default="", description="Suggested K8s workload type (Deployment, StatefulSet)"
    )
    estimated_effort: str = Field(
        default="", description="Estimated effort (low, medium, high)"
    )
    blockers: list[str] = Field(
        default_factory=list, description="Issues that block containerization"
    )


class ContainerizationAnalysis(BaseModel):
    """Complete containerization analysis for all compute resources."""

    recommendations: list[ContainerizationRecommendation] = Field(default_factory=list)
    summary: dict[str, int] = Field(
        default_factory=dict, description="Fitness level → count"
    )
    total_candidates: int = Field(default=0, description="VMs suitable for containerization")
    total_evaluated: int = Field(default=0, description="Total VMs evaluated")


# OS patterns that indicate containerization friendliness
_CONTAINER_FRIENDLY_OS = {
    "ubuntu", "debian", "centos", "rhel", "redhat", "alpine", "fedora", "rocky",
}

# OS patterns that are difficult to containerize
_CONTAINER_UNFRIENDLY_OS = {
    "windows", "aix", "sles", "solaris", "hpux",
}

# Tier patterns that suggest stateless (good for containers)
_STATELESS_TIERS = {"web", "frontend", "proxy", "gateway", "api"}

# Tier patterns that suggest stateful (harder to containerize)
_STATEFUL_TIERS = {"db", "database", "data", "storage"}


class ContainerizationRecommender:
    """Analyzes VMs and recommends which ones are good containerization candidates.

    Evaluation criteria:
    - OS compatibility (Linux preferred, Windows/AIX not recommended)
    - Statefulness (stateless workloads are easier to containerize)
    - Resource sizing (small-to-medium VMs are better candidates)
    - Tier classification (web/app tiers are natural container targets)
    - Dependency complexity (fewer dependencies = easier migration)

    The output is advisory only — it doesn't change the migration pipeline.
    """

    def analyze(self, resources: DiscoveredResources) -> ContainerizationAnalysis:
        """Evaluate all compute resources for containerization fitness.

        Args:
            resources: Discovered resources with compute workloads.

        Returns:
            ContainerizationAnalysis with per-VM recommendations.
        """
        logger.info(
            "containerization_analysis_started",
            compute_count=len(resources.compute),
        )

        recommendations: list[ContainerizationRecommendation] = []

        for vm in resources.compute:
            if vm.type == ComputeType.CONTAINER:
                # Already a container — no recommendation needed
                continue
            rec = self._evaluate_vm(vm)
            recommendations.append(rec)

        # Build summary
        summary: dict[str, int] = {}
        for rec in recommendations:
            summary[rec.fitness.value] = summary.get(rec.fitness.value, 0) + 1

        total_candidates = sum(
            1 for r in recommendations
            if r.fitness in (ContainerizationFitness.EXCELLENT, ContainerizationFitness.GOOD)
        )

        result = ContainerizationAnalysis(
            recommendations=recommendations,
            summary=summary,
            total_candidates=total_candidates,
            total_evaluated=len(recommendations),
        )

        logger.info(
            "containerization_analysis_completed",
            evaluated=len(recommendations),
            candidates=total_candidates,
            summary=summary,
        )
        return result

    def _evaluate_vm(self, vm: ComputeResource) -> ContainerizationRecommendation:
        """Score a VM for containerization fitness."""
        score = 50  # Start neutral
        reasons: list[str] = []
        blockers: list[str] = []

        # Factor 1: OS compatibility
        os_lower = vm.os.lower()
        if any(os_name in os_lower for os_name in _CONTAINER_FRIENDLY_OS):
            score += 15
            reasons.append(f"Linux-based OS ({vm.os}) is container-friendly")
        elif any(os_name in os_lower for os_name in _CONTAINER_UNFRIENDLY_OS):
            score -= 30
            blockers.append(f"OS ({vm.os}) is not container-compatible")

        # Factor 2: Statefulness
        if not vm.stateful:
            score += 15
            reasons.append("Stateless workload — ideal for containers")
        else:
            score -= 10
            reasons.append("Stateful workload — requires StatefulSet with persistent storage")

        # Factor 3: Resource sizing
        if vm.cpu <= 4 and vm.memory_gb <= 16:
            score += 10
            reasons.append(f"Small resource footprint ({vm.cpu} CPU, {vm.memory_gb}GB RAM)")
        elif vm.cpu <= 8 and vm.memory_gb <= 32:
            score += 5
            reasons.append(f"Medium resource footprint ({vm.cpu} CPU, {vm.memory_gb}GB RAM)")
        else:
            score -= 5
            reasons.append(f"Large resource footprint ({vm.cpu} CPU, {vm.memory_gb}GB RAM) — may need resource tuning")

        # Factor 4: Tier classification
        tier = vm.tags.get("tier", "").lower()
        if tier in _STATELESS_TIERS:
            score += 10
            reasons.append(f"Web/API tier ({tier}) — natural container target")
        elif tier in _STATEFUL_TIERS:
            score -= 5
            reasons.append(f"Data tier ({tier}) — containerization is possible but needs careful planning")

        # Factor 5: Storage complexity
        if vm.storage_gb > 500:
            score -= 10
            reasons.append(f"Large root disk ({vm.storage_gb}GB) — data migration overhead")
        if len(vm.disks) > 2:
            score -= 5
            reasons.append(f"Multiple data disks ({len(vm.disks)}) — complex volume mapping")

        # Factor 6: Bare metal
        if vm.type == ComputeType.BAREMETAL:
            score -= 20
            blockers.append("Bare metal workload — requires full rebuild before containerization")

        # Clamp score
        score = max(0, min(100, score))

        # Determine fitness level
        if blockers:
            fitness = ContainerizationFitness.NOT_RECOMMENDED
        elif score >= 75:
            fitness = ContainerizationFitness.EXCELLENT
        elif score >= 55:
            fitness = ContainerizationFitness.GOOD
        elif score >= 35:
            fitness = ContainerizationFitness.POSSIBLE
        else:
            fitness = ContainerizationFitness.NOT_RECOMMENDED

        # Suggest approach
        if fitness in (ContainerizationFitness.EXCELLENT, ContainerizationFitness.GOOD):
            if vm.stateful:
                approach = "Containerize as StatefulSet with PVC-backed persistent storage"
                workload_type = "StatefulSet"
            else:
                approach = "Containerize as Deployment with horizontal scaling"
                workload_type = "Deployment"
            effort = "low" if fitness == ContainerizationFitness.EXCELLENT else "medium"
        elif fitness == ContainerizationFitness.POSSIBLE:
            approach = "Containerization possible but requires refactoring"
            workload_type = "Deployment"
            effort = "high"
        else:
            approach = "Keep as VM — containerization not recommended"
            workload_type = ""
            effort = ""

        return ContainerizationRecommendation(
            resource_name=vm.name,
            resource_id=str(vm.id),
            fitness=fitness,
            score=score,
            reasons=reasons,
            suggested_approach=approach,
            target_workload_type=workload_type,
            estimated_effort=effort,
            blockers=blockers,
        )
