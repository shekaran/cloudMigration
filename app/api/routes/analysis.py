"""Analysis API routes — graph, strategy, validation, and network planning endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import (
    get_discovery_service,
    get_graph_service,
    get_network_planner,
    get_strategy_engine,
    get_validation_engine,
)
from app.core.exceptions import AdapterDiscoveryError, AdapterNotFoundError
from app.graph.engine import DependencyGraph, build_graph
from app.models.responses import ErrorResponse
from app.services.discovery import DiscoveryService
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
) -> dict:
    """Run strategy analysis and network planning on discovered resources.

    Returns strategy assignments per resource and network allocation plan.
    """
    try:
        discovery = await discovery_svc.run(adapter_name)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdapterDiscoveryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    graph = build_graph(discovery.normalized)
    strategy_result = strategy_engine.analyze(discovery.normalized, graph)
    network_plan = network_planner.plan(discovery.normalized.networks)

    return {
        "adapter": adapter_name,
        "strategy": strategy_result.model_dump(),
        "network_plan": network_plan.model_dump(),
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
