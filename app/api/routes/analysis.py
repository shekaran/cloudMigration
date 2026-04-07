"""Analysis API routes — graph, strategy, validation, firewall, network, K8s, and containerization."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import (
    get_containerization_recommender,
    get_discovery_service,
    get_firewall_engine,
    get_graph_service,
    get_k8s_migration_service,
    get_k8s_translation_service,
    get_network_planner,
    get_strategy_engine,
    get_validation_engine,
)
from app.core.exceptions import AdapterDiscoveryError, AdapterNotFoundError
from app.graph.engine import DependencyGraph, build_graph
from app.models.responses import ErrorResponse
from app.services.containerization import ContainerizationRecommender
from app.services.discovery import DiscoveryService
from app.services.firewall_engine import FirewallEngine
from app.services.k8s_migration import K8sMigrationService
from app.services.k8s_translation import K8sTranslationService
from app.services.network_planner import NetworkPlan, NetworkPlanner
from app.services.strategy import StrategyEngine, StrategyResult
from app.services.validation import ValidationEngine, ValidationResult

router = APIRouter(tags=["analysis"])


@router.post(
    "/validate/{adapter_name}",
    responses={
        404: {"model": ErrorResponse, "description": "Adapter not found"},
        500: {"model": ErrorResponse, "description": "Validation failed"},
    },
)
async def validate_resources(
    adapter_name: str,
    discovery_svc: DiscoveryService = Depends(get_discovery_service),
    validation_engine: ValidationEngine = Depends(get_validation_engine),
) -> dict:
    """Run pre-migration validation checks on discovered resources.

    Returns validation findings with severity levels (ERROR, WARNING, INFO).
    """
    try:
        discovery = await discovery_svc.run(adapter_name)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdapterDiscoveryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    graph = build_graph(discovery.normalized)
    result = validation_engine.validate(discovery.normalized, graph)
    return result.model_dump()


@router.post(
    "/analyze/{adapter_name}",
    responses={
        404: {"model": ErrorResponse, "description": "Adapter not found"},
        500: {"model": ErrorResponse, "description": "Analysis failed"},
    },
)
async def analyze_resources(
    adapter_name: str,
    discovery_svc: DiscoveryService = Depends(get_discovery_service),
    strategy_engine: StrategyEngine = Depends(get_strategy_engine),
    network_planner: NetworkPlanner = Depends(get_network_planner),
    firewall_engine: FirewallEngine = Depends(get_firewall_engine),
) -> dict:
    """Run strategy analysis, firewall analysis, and network planning.

    Returns strategy assignments, firewall analysis (conflicts, normalized rules,
    tier groupings), and network allocation plan with tier summaries.
    """
    try:
        discovery = await discovery_svc.run(adapter_name)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdapterDiscoveryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    graph = build_graph(discovery.normalized)
    strategy_result = strategy_engine.analyze(discovery.normalized, graph)
    firewall_result = firewall_engine.analyze(discovery.normalized)
    network_plan = network_planner.plan(
        discovery.normalized.networks, discovery.normalized.compute
    )

    return {
        "adapter": adapter_name,
        "strategy": strategy_result.model_dump(),
        "firewall": firewall_result.model_dump(),
        "network_plan": network_plan.model_dump(),
    }


@router.post(
    "/firewall/{adapter_name}",
    responses={
        404: {"model": ErrorResponse, "description": "Adapter not found"},
        500: {"model": ErrorResponse, "description": "Firewall analysis failed"},
    },
)
async def analyze_firewall(
    adapter_name: str,
    discovery_svc: DiscoveryService = Depends(get_discovery_service),
    firewall_engine: FirewallEngine = Depends(get_firewall_engine),
) -> dict:
    """Run firewall rule analysis on discovered resources.

    Returns normalized rules, conflicts (with resolutions), unsupported rules,
    and rules grouped by tier.
    """
    try:
        discovery = await discovery_svc.run(adapter_name)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdapterDiscoveryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = firewall_engine.analyze(discovery.normalized)
    return {
        "adapter": adapter_name,
        "firewall": result.model_dump(),
    }


@router.get(
    "/graph/{adapter_name}",
    responses={
        404: {"model": ErrorResponse, "description": "Adapter not found"},
    },
)
async def get_dependency_graph(
    adapter_name: str,
    format: str = "json",
    discovery_svc: DiscoveryService = Depends(get_discovery_service),
) -> dict:
    """Get the dependency graph for discovered resources.

    Args:
        adapter_name: Source platform adapter.
        format: Output format — "json" (default) or "dot" (Graphviz).

    Returns:
        Graph as JSON (nodes + edges) or Graphviz DOT string.
    """
    try:
        discovery = await discovery_svc.run(adapter_name)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdapterDiscoveryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    graph = build_graph(discovery.normalized)

    try:
        order = graph.topological_sort()
        stages = graph.parallel_stages()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Graph analysis failed: {exc}"
        ) from exc

    result = {
        "adapter": adapter_name,
        "nodes": len(graph.nodes),
        "edges": graph.edge_count,
        "graph": graph.to_dict(),
        "execution_order": [str(uid) for uid in order],
        "parallel_stages": [
            [str(uid) for uid in stage] for stage in stages
        ],
    }

    if format == "dot":
        result["dot"] = graph.to_dot()

    return result


@router.post(
    "/containerize/{adapter_name}",
    responses={
        404: {"model": ErrorResponse, "description": "Adapter not found"},
        500: {"model": ErrorResponse, "description": "Analysis failed"},
    },
)
async def recommend_containerization(
    adapter_name: str,
    discovery_svc: DiscoveryService = Depends(get_discovery_service),
    recommender: ContainerizationRecommender = Depends(get_containerization_recommender),
) -> dict:
    """Analyze VMs and recommend containerization candidates.

    Returns per-VM fitness scores, suggested approaches, and blockers.
    """
    try:
        discovery = await discovery_svc.run(adapter_name)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdapterDiscoveryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = recommender.analyze(discovery.normalized)
    return {
        "adapter": adapter_name,
        "containerization": result.model_dump(),
    }


@router.post(
    "/k8s/backup/{adapter_name}",
    responses={
        404: {"model": ErrorResponse, "description": "Adapter not found"},
    },
)
async def k8s_backup(
    adapter_name: str,
    discovery_svc: DiscoveryService = Depends(get_discovery_service),
    k8s_migration: K8sMigrationService = Depends(get_k8s_migration_service),
) -> dict:
    """Create a backup of discovered Kubernetes resources.

    Returns backup manifest with captured workload specs and PVC snapshots.
    """
    try:
        discovery = await discovery_svc.run(adapter_name)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdapterDiscoveryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    backup = k8s_migration.backup(discovery.normalized)
    return {
        "adapter": adapter_name,
        "backup": backup.model_dump(),
    }


@router.post(
    "/k8s/translate/{adapter_name}",
    responses={
        404: {"model": ErrorResponse, "description": "Adapter not found"},
    },
)
async def k8s_translate(
    adapter_name: str,
    target_platform: str = "iks",
    discovery_svc: DiscoveryService = Depends(get_discovery_service),
    k8s_translation: K8sTranslationService = Depends(get_k8s_translation_service),
) -> dict:
    """Translate K8s resources to IKS or OpenShift target manifests.

    Args:
        target_platform: "iks" (default) or "openshift".
    """
    try:
        discovery = await discovery_svc.run(adapter_name)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdapterDiscoveryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Override target platform if specified
    k8s_translation._platform = k8s_translation._platform.__class__(target_platform)

    result = k8s_translation.translate(discovery.normalized)
    return {
        "adapter": adapter_name,
        "target_platform": target_platform,
        "cluster": result.cluster.model_dump(mode="json"),
        "workloads": len(result.workloads),
        "services": len(result.services),
        "storage": len(result.storage),
        "manifests": {
            "workloads": [w.manifest for w in result.workloads],
            "services": [s.manifest for s in result.services],
            "storage": [s.manifest for s in result.storage],
        },
    }
